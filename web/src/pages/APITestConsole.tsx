import React, { useState } from "react";
import styles from "./APITestConsole.module.css";

interface Endpoint {
  id: string;
  method: "GET" | "POST" | "PUT" | "DELETE" | "HEAD";
  path: string;
  title: string;
  desc?: string;
  paths?: string[];
  query?: Record<string, string | boolean>;
  body?: Record<string, unknown>;
  upload?: boolean;
}

const endpoints: Endpoint[] = [
  {
    id: "faces",
    method: "GET",
    path: "/api/faces",
    title: "List registered faces",
    desc: "Returns face names mapped to image filenames.",
  },
  {
    id: "face-reprocess",
    method: "POST",
    path: "/api/faces/reprocess",
    title: "Reprocess training image",
    desc: "Admin endpoint. Body: { training_file }.",
    body: { training_file: "" },
  },
  {
    id: "face-train",
    method: "POST",
    path: "/api/faces/train/{name}/classify",
    title: "Classify/save training image",
    desc: "Body can contain training_file or event_id.",
    paths: ["name"],
    body: { training_file: "", event_id: "" },
  },
  {
    id: "face-create",
    method: "POST",
    path: "/api/faces/{name}/create",
    title: "Create face",
    desc: "Admin endpoint. Creates a face folder.",
    paths: ["name"],
  },
  {
    id: "face-register",
    method: "POST",
    path: "/api/faces/{name}/register",
    title: "Register face image",
    desc: "Admin endpoint. Multipart file upload.",
    paths: ["name"],
    upload: true,
  },
  {
    id: "face-recognize",
    method: "POST",
    path: "/api/faces/recognize",
    title: "Recognize face",
    desc: "Uploads an image and compares it with registered faces.",
    upload: true,
  },
  {
    id: "face-reclassify",
    method: "POST",
    path: "/api/faces/{name}/reclassify",
    title: "Move face image to another name",
    desc: "Admin endpoint. Body: { id, new_name }.",
    paths: ["name"],
    body: { id: "", new_name: "" },
  },
  {
    id: "face-delete",
    method: "POST",
    path: "/api/faces/{name}/delete",
    title: "Delete face images",
    desc: "Admin endpoint. Body: { ids: [...] }.",
    paths: ["name"],
    body: { ids: [] },
  },
  {
    id: "face-rename",
    method: "PUT",
    path: "/api/faces/{old_name}/rename",
    title: "Rename face",
    desc: "Admin endpoint. Body: { new_name }.",
    paths: ["old_name"],
    body: { new_name: "" },
  },
  {
    id: "lpr-reprocess",
    method: "PUT",
    path: "/api/lpr/reprocess",
    title: "Reprocess license plate",
    desc: "Query parameter: event_id.",
    query: { event_id: "" },
  },
  {
    id: "reindex",
    method: "PUT",
    path: "/api/reindex",
    title: "Reindex embeddings",
    desc: "Admin endpoint. Starts tracked-object embedding reindexing.",
  },
  {
    id: "audio-transcribe",
    method: "PUT",
    path: "/api/audio/transcribe",
    title: "Transcribe event audio",
    desc: "Body contains event_id.",
    body: { event_id: "" },
  },
  {
    id: "classification-dataset",
    method: "GET",
    path: "/api/classification/{name}/dataset",
    title: "Get classification dataset",
    desc: "Returns categories and training metadata.",
    paths: ["name"],
  },
  {
    id: "classification-attributes",
    method: "GET",
    path: "/api/classification/attributes",
    title: "Get custom attributes",
    desc: "Query: object_type, group_by_model.",
    query: { object_type: "", group_by_model: false },
  },
  {
    id: "classification-train-images",
    method: "GET",
    path: "/api/classification/{name}/train",
    title: "List classification train images",
    desc: "Returns image filenames.",
    paths: ["name"],
  },
  {
    id: "classification-train",
    method: "POST",
    path: "/api/classification/{name}/train",
    title: "Train classification model",
    desc: "Starts model training.",
    paths: ["name"],
  },
  {
    id: "classification-dataset-delete",
    method: "POST",
    path: "/api/classification/{name}/dataset/{category}/delete",
    title: "Delete dataset images",
    desc: "Admin endpoint. Body: { ids: [...] }.",
    paths: ["name", "category"],
    body: { ids: [] },
  },
  {
    id: "classification-dataset-reclassify",
    method: "POST",
    path: "/api/classification/{name}/dataset/{category}/reclassify",
    title: "Reclassify dataset image",
    desc: "Admin endpoint. Body: { id, new_category }.",
    paths: ["name", "category"],
    body: { id: "", new_category: "" },
  },
  {
    id: "classification-category-rename",
    method: "PUT",
    path: "/api/classification/{name}/dataset/{old_category}/rename",
    title: "Rename classification category",
    desc: "Admin endpoint. Body: { new_category }.",
    paths: ["name", "old_category"],
    body: { new_category: "" },
  },
  {
    id: "classification-categorize",
    method: "POST",
    path: "/api/classification/{name}/dataset/categorize",
    title: "Categorize a train image",
    desc: "Admin endpoint. Body: { category, training_file }.",
    paths: ["name"],
    body: { category: "", training_file: "" },
  },
  {
    id: "classification-category-create",
    method: "POST",
    path: "/api/classification/{name}/dataset/{category}/create",
    title: "Create classification category",
    desc: "Admin endpoint. Creates an empty category folder.",
    paths: ["name", "category"],
  },
  {
    id: "classification-train-delete",
    method: "POST",
    path: "/api/classification/{name}/train/delete",
    title: "Delete train images",
    desc: "Admin endpoint. Body: { ids: [...] }.",
    paths: ["name"],
    body: { ids: [] },
  },
  {
    id: "generate-state",
    method: "POST",
    path: "/api/classification/generate_examples/state",
    title: "Generate state examples",
    desc: "Admin endpoint. Body: { model_name, cameras }.",
    body: { model_name: "", cameras: {} },
  },
  {
    id: "generate-object",
    method: "POST",
    path: "/api/classification/generate_examples/object",
    title: "Generate object examples",
    desc: "Admin endpoint. Body: { model_name, label }.",
    body: { model_name: "", label: "" },
  },
  {
    id: "classification-delete",
    method: "DELETE",
    path: "/api/classification/{name}",
    title: "Delete classification model",
    desc: "Admin endpoint. Deletes model data and cache.",
    paths: ["name"],
  },
];

type AuthMode = "cookie" | "bearer" | "none";

interface RequestState {
  pathParams: Record<string, string>;
  queryParams: Record<string, string>;
  jsonBody: string;
  file: File | null;
}

interface ResponseState {
  status: number | null;
  statusText: string;
  body: string;
  timing: number;
  error: string;
}

function defaultBody(ep: Endpoint): string {
  if (!ep.body) return "";
  return JSON.stringify(ep.body, null, 2);
}

export const APITestConsole: React.FC = () => {
  const [selected, setSelected] = useState<Endpoint>(endpoints[0]);
  const [authMode, setAuthMode] = useState<AuthMode>("cookie");
  const [token, setToken] = useState("");
  const [filter, setFilter] = useState("");
  const [requestState, setRequestState] = useState<RequestState>({
    pathParams: {},
    queryParams: {},
    jsonBody: defaultBody(endpoints[0]),
    file: null,
  });
  const [responseState, setResponseState] = useState<ResponseState>({
    status: null,
    statusText: "",
    body: "Send a request to see the response.",
    timing: 0,
    error: "",
  });

  function buildPath(ep: Endpoint): string {
    const values = requestState.pathParams;
    return ep.path.replace(/\{([^}]+)\}/g, (_, key) =>
      encodeURIComponent(values[key] ?? "")
    );
  }

  function buildUrl(ep: Endpoint): string {
    const baseUrl = window.location.origin;
    const url = new URL(baseUrl + buildPath(ep));
    Object.entries(requestState.queryParams).forEach(([key, value]) => {
      if (value !== "") {
        url.searchParams.set(key, value);
      }
    });
    return url.toString();
  }

  function parseBody(): unknown {
    const raw = requestState.jsonBody.trim();
    if (!raw) return undefined;
    return JSON.parse(raw);
  }

  function authHeaders(): Record<string, string> {
    const headers: Record<string, string> = {};
    if (authMode === "bearer" && token.trim()) {
      headers.Authorization = `Bearer ${token}`;
    }
    return headers;
  }

  function pretty(data: string, contentType = ""): string {
    if (contentType.includes("application/json")) {
      try {
        return JSON.stringify(JSON.parse(data), null, 2);
      } catch {
        return String(data);
      }
    }
    return String(data);
  }

  function shellQuote(s: string): string {
    if (/^[A-Za-z0-9_./:{}?=&%-]+$/.test(s)) return s;
    return `'${s.replace(/'/g, `'\\''`)}'`;
  }

  function generateCurl(): string {
    const url = buildUrl(selected);
    const parts = [`curl -X ${selected.method}`, shellQuote(url)];

    Object.entries(authHeaders()).forEach(([k, v]) =>
      parts.push(`-H ${shellQuote(`${k}: ${v}`)}`)
    );

    if (selected.upload) {
      const f = requestState.file?.name || "IMAGE_FILE";
      parts.push(`-F ${shellQuote(`file=@${f}`)}`);
    } else if (
      selected.body &&
      selected.method !== "GET" &&
      selected.method !== "DELETE"
    ) {
      try {
        const body = parseBody();
        if (body !== undefined) {
          parts.push(`-H '"'"'Content-Type: application/json'"'"'`);
          parts.push(`-d ${shellQuote(JSON.stringify(body))}`);
        }
      } catch {
        parts.push("# invalid JSON body");
      }
    }

    return parts.join(" \\\n  ");
  }

  async function sendRequest() {
    const started = performance.now();

    try {
      const url = buildUrl(selected);
      const headers = authHeaders();

      if (selected.method !== "GET" && selected.method !== "HEAD") {
        headers["X-CSRF-Token"] = "1";
      }

      let body: FormData | string | undefined;
      const isMultipart = Boolean(selected.upload);

      if (isMultipart) {
        if (!requestState.file) {
          throw new Error("Choose a file first.");
        }
        const form = new FormData();
        form.append("file", requestState.file);
        body = form;
      } else if (
        selected.body &&
        selected.method !== "GET" &&
        selected.method !== "DELETE"
      ) {
        const parsed = parseBody();
        body = parsed === undefined ? undefined : JSON.stringify(parsed);
        if (body !== undefined) headers["Content-Type"] = "application/json";
      }

      const response = await fetch(url, {
        method: selected.method,
        headers,
        body,
        credentials: authMode === "cookie" ? "include" : "same-origin",
      });

      const contentType = response.headers.get("content-type") || "";
      const raw = await response.text();

      setResponseState({
        status: response.status,
        statusText: response.statusText,
        body: pretty(raw, contentType),
        timing: Math.round(performance.now() - started),
        error: !response.ok
          ? "Request returned a non-2xx status. See the response panel for details."
          : "",
      });
    } catch (err) {
      setResponseState({
        status: null,
        statusText: "Request failed",
        body: "",
        timing: Math.round(performance.now() - started),
        error:
          err instanceof SyntaxError
            ? "Invalid JSON in the request body."
            : String((err as Error)?.message || err),
      });
    }
  }

  const handleSelectEndpoint = (ep: Endpoint) => {
    setSelected(ep);
    const pathParams: Record<string, string> = {};
    (ep.paths || []).forEach((p) => {
      pathParams[p] = "";
    });
    const queryParams: Record<string, string> = {};
    if (ep.query) {
      Object.entries(ep.query).forEach(([key, value]) => {
        queryParams[key] = String(value);
      });
    }
    setRequestState({
      pathParams,
      queryParams,
      jsonBody: defaultBody(ep),
      file: null,
    });
    setResponseState({
      status: null,
      statusText: "",
      body: "Send a request to see the response.",
      timing: 0,
      error: "",
    });
  };

  const filteredEndpoints = endpoints.filter((ep) =>
    `${ep.method} ${ep.path} ${ep.title}`
      .toLowerCase()
      .includes(filter.toLowerCase())
  );

  const statusClass =
    responseState.status === null
      ? "neutral"
      : responseState.status < 400
        ? "ok"
        : responseState.status < 500
          ? "warn"
          : "bad";

  return (
    <div className={styles.container}>
      <header className={styles.topbar}>
        <div>
          <h1>Frigate API Test Console</h1>
          <p>Browser-based tester for the classification / face endpoints.</p>
        </div>
        <div className={styles.topActions}>
          <label className={styles.inlineField}>
            <span>Auth mode</span>
            <select value={authMode} onChange={(e) => setAuthMode(e.target.value as AuthMode)}>
              <option value="cookie">Browser cookies</option>
              <option value="bearer">Bearer token</option>
              <option value="none">No auth</option>
            </select>
          </label>
          {authMode === "bearer" && (
            <label className={styles.inlineField}>
              <span>Bearer token</span>
              <input
                type="password"
                placeholder="token"
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </label>
          )}
        </div>
      </header>

      <main className={styles.layout}>
        <aside className={styles.sidebar}>
          <div className={styles.sectionTitle}>Endpoints</div>
          <input
            className={styles.search}
            placeholder="Filter endpoints..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div className={styles.endpointList}>
            {filteredEndpoints.map((ep) => (
              <button
                key={ep.id}
                className={`${styles.endpoint} ${
                  ep.id === selected.id ? styles.active : ""
                }`}
                onClick={() => handleSelectEndpoint(ep)}
              >
                <div className={styles.method}>{ep.method}</div>
                <div>
                  <div className={styles.epPath}>{ep.path}</div>
                  <div className={styles.epTitle}>{ep.title}</div>
                </div>
              </button>
            ))}
          </div>
        </aside>

        <section className={styles.workspace}>
          <div className={styles.endpointSummary}>
            <div className={styles.methodPill}>{selected.method}</div>
            <div className={styles.summaryMain}>
              <div className={styles.endpointPath}>{selected.path}</div>
              <div className={styles.endpointDesc}>{selected.desc || ""}</div>
            </div>
            <div className={styles.actions}>
              <button className={styles.primary} onClick={sendRequest}>
                Send request
              </button>
              <button onClick={() => handleSelectEndpoint(selected)}>
                Clear
              </button>
            </div>
          </div>

          <div className={styles.grid}>
            <div className={styles.panel}>
              <div className={styles.panelHead}>
                <h2>Request</h2>
                <span className={styles.muted}>
                  {authMode === "cookie"
                    ? "Uses browser cookies"
                    : authMode === "bearer"
                      ? "Authorization header"
                      : "No auth header"}
                </span>
              </div>

              {selected.paths && selected.paths.length > 0 && (
                <div className={styles.pathFields}>
                  {selected.paths.map((pathKey) => (
                    <div key={pathKey} className={styles.fieldRow}>
                      <label>{pathKey}</label>
                      <input
                        type="text"
                        value={requestState.pathParams[pathKey] || ""}
                        onChange={(e) =>
                          setRequestState((prev) => ({
                            ...prev,
                            pathParams: {
                              ...prev.pathParams,
                              [pathKey]: e.target.value,
                            },
                          }))
                        }
                      />
                    </div>
                  ))}
                </div>
              )}

              {selected.query && Object.keys(selected.query).length > 0 && (
                <div className={styles.querySection}>
                  <div className={styles.subhead}>Query parameters</div>
                  <div>
                    {Object.entries(selected.query).map(([key, value]) => (
                      <div key={key} className={styles.fieldRow}>
                        <label>{key}</label>
                        {typeof value === "boolean" ? (
                          <input
                            type="checkbox"
                            checked={requestState.queryParams[key] === "true"}
                            onChange={(e) =>
                              setRequestState((prev) => ({
                                ...prev,
                                queryParams: {
                                  ...prev.queryParams,
                                  [key]: e.target.checked ? "true" : "false",
                                },
                              }))
                            }
                            style={{ width: "18px" }}
                          />
                        ) : (
                          <input
                            type="text"
                            value={requestState.queryParams[key] || ""}
                            onChange={(e) =>
                              setRequestState((prev) => ({
                                ...prev,
                                queryParams: {
                                  ...prev.queryParams,
                                  [key]: e.target.value,
                                },
                              }))
                            }
                          />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {selected.body && (
                <div className={styles.bodySection}>
                  <div className={styles.subhead}>JSON body</div>
                  <textarea
                    placeholder='{"key":"value"}'
                    spellCheck="false"
                    value={requestState.jsonBody}
                    onChange={(e) =>
                      setRequestState((prev) => ({
                        ...prev,
                        jsonBody: e.target.value,
                      }))
                    }
                  />
                </div>
              )}

              {selected.upload && (
                <div className={styles.uploadSection}>
                  <div className={styles.subhead}>File upload</div>
                  <input
                    type="file"
                    onChange={(e) =>
                      setRequestState((prev) => ({
                        ...prev,
                        file: e.target.files?.[0] || null,
                      }))
                    }
                  />
                  <div className={styles.hint}>
                    Expected multipart field name: file
                  </div>
                </div>
              )}

              <details>
                <summary>Equivalent cURL</summary>
                <pre className={styles.curlPreview}>{generateCurl()}</pre>
              </details>
            </div>

            <div className={styles.panel}>
              <div className={styles.panelHead}>
                <h2>Response</h2>
                <div>
                  <span className={`${styles.status} ${styles[statusClass]}`}>
                    {responseState.status
                      ? `${responseState.status} ${responseState.statusText}`
                      : "Not sent"}
                  </span>
                  {responseState.timing > 0 && (
                    <span className={styles.muted}>
                      {responseState.timing} ms
                    </span>
                  )}
                </div>
              </div>
              {responseState.error && (
                <div className={styles.errorBox}>{responseState.error}</div>
              )}
              <pre className={styles.response}>{responseState.body}</pre>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
};

export default APITestConsole;
