import logging
import hashlib
import os
import queue
import threading
from pathlib import Path
from abc import ABC, abstractmethod

import cv2
import numpy as np
from scipy import stats

from frigate.config import FrigateConfig
from frigate.const import FACE_DIR, MODEL_CACHE_DIR
from frigate.embeddings.onnx.face_embedding import ArcfaceEmbedding, FaceNetEmbedding
from frigate.log import redirect_output_to_logger
from frigate.util.path import safe_join, sanitize_path_component

logger = logging.getLogger(__name__)


class FaceRecognizer(ABC):
    """Face recognition runner."""

    def __init__(self, config: FrigateConfig) -> None:
        self.config = config
        self.landmark_detector: cv2.face.Facemark | None = None
        self.identity_cache: dict[str, tuple[str, np.ndarray]] = {}
        self.embedding_lock = threading.Lock()
        self.init_landmark_detector()

    @abstractmethod
    def build(self) -> None:
        """Build face recognition model."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear current built model."""
        pass

    @abstractmethod
    def classify(self, face_image: np.ndarray) -> tuple[str, float] | None:
        pass

    @redirect_output_to_logger(logger, logging.DEBUG)  # type: ignore[misc]
    def init_landmark_detector(self) -> None:
        landmark_model = os.path.join(MODEL_CACHE_DIR, "facedet/landmarkdet.yaml")

        if os.path.exists(landmark_model):
            landmark_detector = cv2.face.createFacemarkLBF()
            landmark_detector.loadModel(landmark_model)
            self.landmark_detector = landmark_detector

    def align_face(
        self,
        image: np.ndarray,
        output_width: int,
        output_height: int,
    ) -> np.ndarray:
        if not self.landmark_detector:
            raise ValueError("Landmark detector not initialized")

        # landmark is run on grayscale images
        if image.ndim == 3:
            land_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            land_image = image

        _, lands = self.landmark_detector.fit(
            land_image, np.array([(0, 0, land_image.shape[1], land_image.shape[0])])
        )
        landmarks: np.ndarray = lands[0][0]

        # get landmarks for eyes
        leftEyePts = landmarks[42:48]
        rightEyePts = landmarks[36:42]

        # compute the center of mass for each eye
        leftEyeCenter = leftEyePts.mean(axis=0).astype("int")
        rightEyeCenter = rightEyePts.mean(axis=0).astype("int")

        # compute the angle between the eye centroids
        dY = rightEyeCenter[1] - leftEyeCenter[1]
        dX = rightEyeCenter[0] - leftEyeCenter[0]
        angle = np.degrees(np.arctan2(dY, dX)) - 180

        # compute the desired right eye x-coordinate based on the
        # desired x-coordinate of the left eye
        desiredRightEyeX = 1.0 - 0.35

        # determine the scale of the new resulting image by taking
        # the ratio of the distance between eyes in the *current*
        # image to the ratio of distance between eyes in the
        # *desired* image
        dist = np.sqrt((dX**2) + (dY**2))
        desiredDist = desiredRightEyeX - 0.35
        desiredDist *= output_width
        scale = desiredDist / dist

        # compute center (x, y)-coordinates (i.e., the median point)
        # between the two eyes in the input image
        # grab the rotation matrix for rotating and scaling the face
        eyesCenter = (
            int((leftEyeCenter[0] + rightEyeCenter[0]) // 2),
            int((leftEyeCenter[1] + rightEyeCenter[1]) // 2),
        )
        M = cv2.getRotationMatrix2D(eyesCenter, angle, scale)

        # update the translation component of the matrix
        tX = output_width * 0.5
        tY = output_height * 0.35
        M[0, 2] += tX - eyesCenter[0]
        M[1, 2] += tY - eyesCenter[1]

        # apply the affine transformation
        return cv2.warpAffine(
            image, M, (output_width, output_height), flags=cv2.INTER_CUBIC
        )

    def get_blur_confidence_reduction(self, input: np.ndarray) -> float:
        """Calculates the reduction in confidence based on the blur of the image."""
        if not self.config.face_recognition.blur_confidence_filter:
            return 0.0

        variance = cv2.Laplacian(input, cv2.CV_64F).var()
        logger.debug(f"face detected with blurriness {variance}")

        if variance < 120:  # image is very blurry
            return 0.06
        elif variance < 160:  # image moderately blurry
            return 0.04
        elif variance < 200:  # image is slightly blurry
            return 0.02
        elif variance < 250:  # image is mostly clear
            return 0.01
        else:
            return 0.0

    def embed_face(self, image: np.ndarray) -> np.ndarray:
        """Share alignment and model instances safely with classifier building."""
        with self.embedding_lock:
            aligned = self.align_face(image, image.shape[1], image.shape[0])
            return self.face_embedder([aligned])[0].squeeze()

    def verify_identity(self, face_image: np.ndarray, name: str, signature: str) -> float | None:
        """Compare only the requested identity using the loaded face embedder.

        The existing classifier remains an all-label search. Portal verification
        deliberately accesses a single class mean and never searches other labels.
        """
        if not self.landmark_detector:
            return None
        folder = safe_join(FACE_DIR, name)
        if folder is None or name == "train" or sanitize_path_component(name) != name:
            return None
        path = Path(folder)
        if not path.is_dir() or path.is_symlink():
            return None
        files = sorted(
            (item.name, item.stat().st_size, item.stat().st_mtime_ns)
            for item in path.iterdir()
            if item.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            and item.is_file() and not item.is_symlink() and item.stat().st_size > 0
        )
        current_signature = hashlib.sha256(repr(files).encode()).hexdigest()
        if not files or current_signature != signature:
            return None
        cached = self.identity_cache.get(name)
        if cached is None or cached[0] != signature:
            embeddings = []
            for filename, _, _ in files:
                reference = cv2.imread(str(path / filename))
                if reference is None:
                    continue
                embeddings.append(self.embed_face(reference))
            if not embeddings:
                return None
            # Reuse the existing training and scoring helpers. A versioned
            # target cache cannot be overwritten by an older classifier build.
            mean = build_class_mean(embeddings)
            self.identity_cache[name] = (signature, mean)
        else:
            mean = cached[1]
        embedding = self.embed_face(face_image)
        denominator = np.linalg.norm(embedding) * np.linalg.norm(mean)
        if not np.isfinite(denominator) or denominator <= 0:
            return None
        similarity = float(np.dot(embedding, mean) / denominator)
        median = 0.5 if isinstance(self, FaceNetRecognizer) else 0.3
        confidence = similarity_to_confidence(similarity, median=median)
        return max(0.0, round(confidence - self.get_blur_confidence_reduction(face_image), 2))


def build_class_mean(
    embs: list[np.ndarray],
    trim: float = 0.15,
    outlier_threshold: float = 0.30,
    min_keep_frac: float = 0.7,
    max_iters: int = 3,
) -> np.ndarray:
    """Build a class-mean embedding with two-layer outlier protection.

    Layer 1 (iterative, vector-wise): drop whole embeddings whose cosine
    similarity to the current class mean is below ``outlier_threshold``.
    Catches mislabeled or corrupted training samples (wrong face in the
    folder, full-frame screenshots, extreme crops) that per-dimension
    trimming cannot detect.

    Layer 2 (per-dimension): ``scipy.stats.trim_mean`` on the retained set
    to smooth per-component noise (lighting, expression, alignment jitter).

    Collections with fewer than 5 images bypass outlier rejection — too few
    samples to establish a reliable class center.
    """
    arr = np.stack(embs, axis=0)

    if len(arr) < 5:
        return np.asarray(stats.trim_mean(arr, trim, axis=0))

    keep = np.ones(len(arr), dtype=bool)
    floor = max(5, int(np.ceil(min_keep_frac * len(arr))))

    for _ in range(max_iters):
        mean = stats.trim_mean(arr[keep], trim, axis=0)
        m_norm = mean / (np.linalg.norm(mean) + 1e-9)
        e_norms = arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)
        cos = e_norms @ m_norm
        new_keep = cos >= outlier_threshold

        if new_keep.sum() < floor:
            top = np.argsort(-cos)[:floor]
            new_keep = np.zeros(len(arr), dtype=bool)
            new_keep[top] = True

        if np.array_equal(new_keep, keep):
            break
        keep = new_keep

    dropped = int((~keep).sum())

    if dropped:
        logger.debug(
            f"Vector-wise outlier filter dropped {dropped}/{len(arr)} embeddings"
        )

    return np.asarray(stats.trim_mean(arr[keep], trim, axis=0))


def similarity_to_confidence(
    cosine_similarity: float,
    median: float = 0.3,
    range_width: float = 0.6,
    slope_factor: float = 12,
) -> float:
    """
    Default sigmoid function to map cosine similarity to confidence.

    Args:
        cosine_similarity (float): The input cosine similarity.
        median (float): Assumed median of cosine similarity distribution.
        range_width (float): Assumed range of cosine similarity distribution (90th percentile - 10th percentile).
        slope_factor (float): Adjusts the steepness of the curve.

    Returns:
        float: The confidence score.
    """

    # Calculate slope and bias
    slope = slope_factor / range_width
    bias = median

    # Calculate confidence
    confidence: float = 1 / (1 + np.exp(-slope * (cosine_similarity - bias)))
    return confidence


class FaceNetRecognizer(FaceRecognizer):
    def __init__(self, config: FrigateConfig):
        super().__init__(config)
        self.mean_embs: dict[str, np.ndarray] = {}
        self.face_embedder: FaceNetEmbedding = FaceNetEmbedding()
        self.model_builder_queue: queue.Queue | None = None

    def clear(self) -> None:
        self.mean_embs = {}
        self.identity_cache.clear()

    def run_build_task(self) -> None:
        self.model_builder_queue = queue.Queue()

        def build_model() -> None:
            face_embeddings_map: dict[str, list[np.ndarray]] = {}
            idx = 0

            dir = FACE_DIR
            for name in os.listdir(dir):
                if name == "train":
                    continue

                face_folder = os.path.join(dir, name)

                if not os.path.isdir(face_folder):
                    continue

                face_embeddings_map[name] = []
                for image in os.listdir(face_folder):
                    img = cv2.imread(os.path.join(face_folder, image))

                    if img is None:
                        continue  # type: ignore[unreachable]

                    emb = self.embed_face(img)
                    face_embeddings_map[name].append(emb)

                idx += 1

            assert self.model_builder_queue is not None
            self.model_builder_queue.put(face_embeddings_map)

        thread = threading.Thread(target=build_model, daemon=True)
        thread.start()

    def build(self) -> None:
        if not self.landmark_detector:
            self.init_landmark_detector()
            return None

        if self.model_builder_queue is not None:
            try:
                face_embeddings_map: dict[str, list[np.ndarray]] = (
                    self.model_builder_queue.get(timeout=0.1)
                )
                self.model_builder_queue = None
            except queue.Empty:
                return
        else:
            self.run_build_task()
            return

        if not face_embeddings_map:
            return

        for name, embs in face_embeddings_map.items():
            if embs:
                self.mean_embs[name] = build_class_mean(embs)

        logger.debug("Finished building ArcFace model")

    def classify(self, face_image: np.ndarray) -> tuple[str, float] | None:
        if not self.landmark_detector:
            return None

        if not self.mean_embs:
            self.build()

            if not self.mean_embs:
                return None

        # face recognition is best run on grayscale images

        # get blur factor before aligning face
        blur_reduction = self.get_blur_confidence_reduction(face_image)

        # align face and run recognition
        embedding = self.embed_face(face_image)

        score: float = 0
        label = ""

        for name, mean_emb in self.mean_embs.items():
            dot_product = np.dot(embedding, mean_emb)
            magnitude_A = np.linalg.norm(embedding)
            magnitude_B = np.linalg.norm(mean_emb)

            cosine_similarity = dot_product / (magnitude_A * magnitude_B)
            confidence = similarity_to_confidence(
                cosine_similarity, median=0.5, range_width=0.6
            )

            if confidence > score:
                score = confidence
                label = name

        return label, max(0, round(score - blur_reduction, 2))


class ArcFaceRecognizer(FaceRecognizer):
    def __init__(self, config: FrigateConfig):
        super().__init__(config)
        self.mean_embs: dict[str, np.ndarray] = {}
        self.face_embedder: ArcfaceEmbedding = ArcfaceEmbedding(config.face_recognition)
        self.model_builder_queue: queue.Queue | None = None

    def clear(self) -> None:
        self.mean_embs = {}
        self.identity_cache.clear()

    def run_build_task(self) -> None:
        self.model_builder_queue = queue.Queue()

        def build_model() -> None:
            face_embeddings_map: dict[str, list[np.ndarray]] = {}
            idx = 0

            dir = FACE_DIR
            for name in os.listdir(dir):
                if name == "train":
                    continue

                face_folder = os.path.join(dir, name)

                if not os.path.isdir(face_folder):
                    continue

                face_embeddings_map[name] = []
                for image in os.listdir(face_folder):
                    img = cv2.imread(os.path.join(face_folder, image))

                    if img is None:
                        continue  # type: ignore[unreachable]

                    emb = self.embed_face(img)
                    face_embeddings_map[name].append(emb)

                idx += 1

            assert self.model_builder_queue is not None
            self.model_builder_queue.put(face_embeddings_map)

        thread = threading.Thread(target=build_model, daemon=True)
        thread.start()

    def build(self) -> None:
        if not self.landmark_detector:
            self.init_landmark_detector()
            return None

        if self.model_builder_queue is not None:
            try:
                face_embeddings_map: dict[str, list[np.ndarray]] = (
                    self.model_builder_queue.get(timeout=0.1)
                )
                self.model_builder_queue = None
            except queue.Empty:
                return
        else:
            self.run_build_task()
            return

        if not face_embeddings_map:
            return

        for name, embs in face_embeddings_map.items():
            if embs:
                self.mean_embs[name] = build_class_mean(embs)

        logger.debug("Finished building ArcFace model")

    def classify(self, face_image: np.ndarray) -> tuple[str, float] | None:
        if not self.landmark_detector:
            return None

        if not self.mean_embs:
            self.build()

            if not self.mean_embs:
                return None

        # face recognition is best run on grayscale images

        # get blur reduction before aligning face
        blur_reduction = self.get_blur_confidence_reduction(face_image)

        # align face and run recognition
        embedding = self.embed_face(face_image)

        score: float = 0
        label = ""

        for name, mean_emb in self.mean_embs.items():
            dot_product = np.dot(embedding, mean_emb)
            magnitude_A = np.linalg.norm(embedding)
            magnitude_B = np.linalg.norm(mean_emb)

            cosine_similarity = dot_product / (magnitude_A * magnitude_B)
            confidence = similarity_to_confidence(cosine_similarity)

            if confidence > score:
                score = confidence
                label = name

        return label, max(0, round(score - blur_reduction, 2))
