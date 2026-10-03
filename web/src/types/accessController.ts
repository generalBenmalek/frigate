export type AccessEvent = {
  id: string;
  device_id: string;
  device_name?: string;
  timestamp: number;
  user_name?: string | null;
  user_id?: string | number | null;
  card_number?: string | null;
  door_id?: string | number | null;
  reader_id?: string | number | null;
  status: string;
  authentication_method?: string | number | null;
  verify_mode?: string | number | null;
  error_code?: string | number | null;
  type?: string | null;
  owner_names?: string[];
  verification_status?:
    | "pending"
    | "unverified"
    | "valid"
    | "warning"
    | "unknown";
  machine_status?: "pending" | "unverified" | AccessClassification;
  effective_status?: "pending" | "unverified" | AccessClassification;
  review_status?: AccessClassification | null;
  reviewed?: boolean;
  reviewed_at?: number | null;
  reviewed_by?: string | null;
  review_revision?: number;
  source?: "controller" | "employee_portal";
  employee_id?: string | null;
  portal_request_id?: string | null;
  verification_reason?: string | null;
  verification_sources?: string[];
  evidence_time?: number;
  clock_adjusted?: boolean;
  snapshots?: { url: string; timestamp: number }[];
  people?: {
    event_id: string;
    name: string;
    start_time: number;
    end_time: number | null;
    source?: string;
    has_clip?: boolean;
    has_snapshot?: boolean;
  }[];
  camera?: string | null;
  clip_start?: number;
  clip_end?: number;
  raw?: Record<string, unknown>;
};

export type AccessEventFilters = {
  start: string;
  end: string;
  name: string;
  userId: string;
  cardNo: string;
  status: "" | "OK" | "Failed";
};

export const emptyAccessEventFilters: AccessEventFilters = {
  start: "",
  end: "",
  name: "",
  userId: "",
  cardNo: "",
  status: "",
};

export type AccessClassification = "valid" | "warning" | "unknown";

export type AccessReviewFilters = {
  start: string;
  end: string;
  name: string;
  userId: string;
  cardNo: string;
  deviceId: string;
  doorId: string;
  camera: string;
  source: "" | "controller" | "employee_portal";
  reviewed: "all" | "reviewed" | "unreviewed";
  classification: "" | AccessClassification | "pending";
};

export const emptyAccessReviewFilters: AccessReviewFilters = {
  start: "",
  end: "",
  name: "",
  userId: "",
  cardNo: "",
  deviceId: "",
  doorId: "",
  camera: "",
  source: "",
  reviewed: "unreviewed",
  classification: "",
};

export type AccessReviewResult = {
  events: AccessEvent[];
  total: number;
  counts: Record<AccessClassification | "pending" | "all", number>;
  page: number;
  page_size: number;
};

export type AccessReviewHistory = {
  id: number;
  event_id: string;
  revision: number;
  reviewer: string;
  reviewed_at: number;
  previous_status: string;
  status: AccessClassification;
  action: "confirm" | "correct";
};
