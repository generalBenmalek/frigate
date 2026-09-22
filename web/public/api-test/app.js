const $ = (id) => document.getElementById(id);

const endpoints = [
  { id:"faces", method:"GET", path:"/api/faces", title:"List registered faces", desc:"Returns face names mapped to image filenames." },

  { id:"face-reprocess", method:"POST", path:"/api/faces/reprocess", title:"Reprocess training image", desc:"Admin endpoint. Body: { training_file }.", body:{training_file:""} },

  { id:"face-train", method:"POST", path:"/api/faces/train/{name}/classify", title:"Classify/save training image", desc:"Body can contain training_file or event_id.", paths:["name"], body:{training_file:"",event_id:""} },

  { id:"face-create", method:"POST", path:"/api/faces/{name}/create", title:"Create face", desc:"Admin endpoint. Creates a face folder.", paths:["name"] },

  { id:"face-register", method:"POST", path:"/api/faces/{name}/register", title:"Register face image", desc:"Admin endpoint. Multipart file upload.", paths:["name"], upload:true },

  { id:"face-recognize", method:"POST", path:"/api/faces/recognize", title:"Recognize face", desc:"Uploads an image and compares it with registered faces.", upload:true },

  { id:"face-reclassify", method:"POST", path:"/api/faces/{name}/reclassify", title:"Move face image to another name", desc:"Admin endpoint. Body: { id, new_name }.", paths:["name"], body:{id:"",new_name:""} },

  { id:"face-delete", method:"POST", path:"/api/faces/{name}/delete", title:"Delete face images", desc:"Admin endpoint. Body: { ids: [...] }.", paths:["name"], body:{ids:[]} },

  { id:"face-rename", method:"PUT", path:"/api/faces/{old_name}/rename", title:"Rename face", desc:"Admin endpoint. Body: { new_name }.", paths:["old_name"], body:{new_name:""} },

  { id:"lpr-reprocess", method:"PUT", path:"/api/lpr/reprocess", title:"Reprocess license plate", desc:"Query parameter: event_id.", query:{event_id:""} },

  { id:"reindex", method:"PUT", path:"/api/reindex", title:"Reindex embeddings", desc:"Admin endpoint. Starts tracked-object embedding reindexing." },

  { id:"audio-transcribe", method:"PUT", path:"/api/audio/transcribe", title:"Transcribe event audio", desc:"Body contains event_id.", body:{event_id:""} },

  { id:"classification-dataset", method:"GET", path:"/api/classification/{name}/dataset", title:"Get classification dataset", desc:"Returns categories and training metadata.", paths:["name"] },

  { id:"classification-attributes", method:"GET", path:"/api/classification/attributes", title:"Get custom attributes", desc:"Query: object_type, group_by_model.", query:{object_type:"",group_by_model:false} },

  { id:"classification-train-images", method:"GET", path:"/api/classification/{name}/train", title:"List classification train images", desc:"Returns image filenames.", paths:["name"] },

  { id:"classification-train", method:"POST", path:"/api/classification/{name}/train", title:"Train classification model", desc:"Starts model training.", paths:["name"] },

  { id:"classification-dataset-delete", method:"POST", path:"/api/classification/{name}/dataset/{category}/delete", title:"Delete dataset images", desc:"Admin endpoint. Body: { ids: [...] }.", paths:["name","category"], body:{ids:[]} },

  { id:"classification-dataset-reclassify", method:"POST", path:"/api/classification/{name}/dataset/{category}/reclassify", title:"Reclassify dataset image", desc:"Admin endpoint. Body: { id, new_category }.", paths:["name","category"], body:{id:"",new_category:""} },

  { id:"classification-category-rename", method:"PUT", path:"/api/classification/{name}/dataset/{old_category}/rename", title:"Rename classification category", desc:"Admin endpoint. Body: { new_category }.", paths:["name","old_category"], body:{new_category:""} },

  { id:"classification-categorize", method:"POST", path:"/api/classification/{name}/dataset/categorize", title:"Categorize a train image", desc:"Admin endpoint. Body: { category, training_file }.", paths:["name"], body:{category:"",training_file:""} },

  { id:"classification-category-create", method:"POST", path:"/api/classification/{name}/dataset/{category}/create", title:"Create classification category", desc:"Admin endpoint. Creates an empty category folder.", paths:["name","category"] },

  { id:"classification-train-delete", method:"POST", path:"/api/classification/{name}/train/delete", title:"Delete train images", desc:"Admin endpoint. Body: { ids: [...] }.", paths:["name"], body:{ids:[]} },

  { id:"generate-state", method:"POST", path:"/api/classification/generate_examples/state", title:"Generate state examples", desc:"Admin endpoint. Body: { model_name, cameras }.", body:{model_name:"",cameras:{}} },

  { id:"generate-object", method:"POST", path:"/api/classification/generate_examples/object", title:"Generate object examples", desc:"Admin endpoint. Body: { model_name, label }.", body:{model_name:"",label:""} },

  { id:"classification-delete", method:"DELETE", path:"/api/classification/{name}", title:"Delete classification model", desc:"Admin endpoint. Deletes model data and cache.", paths:["name"] },
];

let selected = endpoints[0];

function normalizedBase() {
  return window.location.origin;
}

function pathTemplateValues(ep) {
  const values = {};
  (ep.paths || []).forEach((p) => {
    const el = document.querySelector(`[data-path="${p}"]`);
    values[p] = el?.value.trim() || "";
  });
  return values;
}

function buildPath(ep) {
  const values = pathTemplateValues(ep);
  return ep.path.replace(/\{([^}]+)\}/g, (_, key) => encodeURIComponent(values[key] ?? ""));
}

function buildUrl(ep) {
  const url = new URL(normalizedBase() + buildPath(ep), window.location.href);
  document.querySelectorAll("[data-query]").forEach((el) => {
    const key = el.dataset.query;
    let value = el.value;
    if (el.type === "checkbox") value = el.checked ? "true" : "false";
    if (value !== "" && value != null) url.searchParams.set(key, value);
  });
  return url.toString();
}

function defaultBody(ep) {
  if (!ep.body) return "";
  return JSON.stringify(ep.body, null, 2);
}

function renderList() {
  const filter = $("filter").value.toLowerCase().trim();
  const list = $("endpointList");
  list.innerHTML = "";
  endpoints
    .filter(ep => `${ep.method} ${ep.path} ${ep.title}`.toLowerCase().includes(filter))
    .forEach(ep => {
      const b = document.createElement("button");
      b.className = `endpoint ${ep.id === selected.id ? "active" : ""}`;
      b.innerHTML = `<div class="method">${ep.method}</div><div><div class="ep-path">${ep.path}</div><div class="ep-title">${ep.title}</div></div>`;
      b.onclick = () => selectEndpoint(ep);
      list.appendChild(b);
    });
}

function renderField(container, label, key, value, opts = {}) {
  const row = document.createElement("div");
  row.className = "field-row";
  const l = document.createElement("label");
  l.textContent = label;
  row.appendChild(l);

  let control;
  if (opts.boolean) {
    control = document.createElement("input");
    control.type = "checkbox";
    control.checked = Boolean(value);
    control.dataset.query = key;
    control.style.width = "18px";
  } else {
    control = document.createElement("input");
    control.value = value ?? "";
    if (opts.path) control.dataset.path = key;
    if (opts.query) control.dataset.query = key;
  }
  row.appendChild(control);
  container.appendChild(row);
}

function selectEndpoint(ep) {
  selected = ep;
  $("methodPill").textContent = ep.method;
  $("endpointPath").textContent = ep.path;
  $("endpointDesc").textContent = ep.desc || "";
  $("jsonBody").value = defaultBody(ep);

  const paths = $("pathFields");
  paths.innerHTML = "";
  (ep.paths || []).forEach(p => renderField(paths, p, p, "", {path:true}));

  const query = $("queryFields");
  query.innerHTML = "";
  if (ep.query) {
    Object.entries(ep.query).forEach(([key, value]) =>
      renderField(query, key, key, value, {query:true, boolean:typeof value === "boolean"})
    );
    $("querySection").classList.remove("hidden");
  } else {
    $("querySection").classList.add("hidden");
  }

  if (ep.body) $("bodySection").classList.remove("hidden");
  else $("bodySection").classList.add("hidden");

  if (ep.upload) {
    $("uploadSection").classList.remove("hidden");
    $("fileInput").value = "";
    $("uploadHint").textContent = "Expected multipart field name: file";
  } else {
    $("uploadSection").classList.add("hidden");
  }

  $("formFields").innerHTML = "";
  $("response").textContent = "Send a request to see the response.";
  $("statusBadge").textContent = "Not sent";
  $("statusBadge").className = "status neutral";
  $("timing").textContent = "";
  $("errorBox").classList.add("hidden");
  updateCurl();
  renderList();
}

function parseBody() {
  const raw = $("jsonBody").value.trim();
  if (!raw) return undefined;
  return JSON.parse(raw);
}

function authHeaders() {
  const mode = $("authMode").value;
  const headers = {};
  if (mode === "bearer") {
    const token = $("token").value.trim();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

function pretty(data, contentType="") {
  if (contentType.includes("application/json") || typeof data === "object") {
    try {
      return JSON.stringify(typeof data === "string" ? JSON.parse(data) : data, null, 2);
    } catch {}
  }
  return String(data);
}

async function sendRequest() {
  $("sendBtn").disabled = true;
  $("errorBox").classList.add("hidden");
  const started = performance.now();

  try {
    const url = buildUrl(selected);
    const headers = authHeaders();

    if (selected.method !== "GET" && selected.method !== "HEAD") {
       headers["X-CSRF-Token"] = "1";
    }
    
    let body;
    let isMultipart = Boolean(selected.upload);

    if (isMultipart) {
      const file = $("fileInput").files[0];
      if (!file) throw new Error("Choose a file first.");
      const form = new FormData();
      form.append("file", file);
      body = form;
    } else if (selected.body && selected.method !== "GET" && selected.method !== "DELETE") {
      const parsed = parseBody();
      body = parsed === undefined ? undefined : JSON.stringify(parsed);
      if (body !== undefined) headers["Content-Type"] = "application/json";
    }

    const response = await fetch(url, {
      method: selected.method,
      headers,
      body,
      credentials: $("authMode").value === "cookie" ? "include" : "same-origin"
    });

    const contentType = response.headers.get("content-type") || "";
    const raw = await response.text();

    $("response").textContent = pretty(raw, contentType);
    $("statusBadge").textContent = `${response.status} ${response.statusText}`;
    $("statusBadge").className = `status ${response.ok ? "ok" : response.status < 500 ? "warn" : "bad"}`;
    $("timing").textContent = `${Math.round(performance.now() - started)} ms`;

    if (!response.ok) {
      $("errorBox").textContent = "Request returned a non-2xx status. See the response panel for details.";
      $("errorBox").classList.remove("hidden");
    }
  } catch (err) {
    $("response").textContent = "";
    $("statusBadge").textContent = "Request failed";
    $("statusBadge").className = "status bad";
    $("timing").textContent = `${Math.round(performance.now() - started)} ms`;
    $("errorBox").textContent = err instanceof SyntaxError
      ? "Invalid JSON in the request body."
      : String(err?.message || err);
    $("errorBox").classList.remove("hidden");
  } finally {
    $("sendBtn").disabled = false;
  }
}

function shellQuote(s) {
  if (/^[A-Za-z0-9_./:{}?=&%-]+$/.test(s)) return s;
  return `'${s.replace(/'/g, "'\\''")}'`;
}

function updateCurl() {
  const url = buildUrl(selected);
  const parts = [`curl -X ${selected.method}`, shellQuote(url)];

  Object.entries(authHeaders()).forEach(([k,v]) => parts.push(`-H ${shellQuote(`${k}: ${v}`)}`));

  if (selected.upload) {
    const f = $("fileInput").files[0]?.name || "IMAGE_FILE";
    parts.push(`-F ${shellQuote(`file=@${f}`)}`);
  } else if (selected.body && selected.method !== "GET" && selected.method !== "DELETE") {
    try {
      const body = parseBody();
      if (body !== undefined) {
        parts.push(`-H 'Content-Type: application/json'`);
        parts.push(`-d ${shellQuote(JSON.stringify(body))}`);
      }
    } catch {
      parts.push("# invalid JSON body");
    }
  }

  $("curlPreview").textContent = parts.join(" \\\n  ");
}

$("sendBtn").onclick = sendRequest;
$("filter").oninput = renderList;
$("baseUrl").oninput = updateCurl;
$("authMode").onchange = () => {
  $("tokenWrap").classList.toggle("hidden", $("authMode").value !== "bearer");
  $("authNote").textContent = $("authMode").value === "cookie"
    ? "Uses browser cookies"
    : $("authMode").value === "bearer" ? "Authorization header" : "No auth header";
  updateCurl();
};
$("token").oninput = updateCurl;
$("jsonBody").oninput = updateCurl;
$("fileInput").onchange = updateCurl;
document.addEventListener("input", (e) => {
  if (e.target.matches("[data-path], [data-query]")) updateCurl();
});
$("clearBtn").onclick = () => selectEndpoint(selected);

$("authMode").dispatchEvent(new Event("change"));
selectEndpoint(selected);
