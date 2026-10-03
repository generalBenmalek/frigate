import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { EmployeeAccessOption, EmployeeAccessResult, EmployeeSession } from "@/types/employee";
import { Camera, LogOut, Lock, AlertCircle, CheckCircle, Loader } from "lucide-react";

class PortalError extends Error {
  constructor(public reason: string, public status: number) {
    super(reason);
  }
}

async function portalRequest<T>(path: string, csrf?: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/employee/${path}`, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: body === undefined ? {} : {
      "Content-Type": "application/json",
      "X-CSRF-TOKEN": csrf ?? "",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new PortalError(data.reason ?? "verification_failed", response.status);
  return data as T;
}

/* ---------- Shared field styling (light theme) ---------- */
const inputClass =
  "h-10 border-slate-300 bg-white text-slate-900 placeholder:text-slate-400 " +
  "focus-visible:border-[#088141] focus-visible:ring-2 focus-visible:ring-[#088141]/20";

const triggerClass =
  "h-10 w-full border-slate-300 bg-white text-slate-900 data-[placeholder]:text-slate-400 " +
  "focus:ring-2 focus:ring-[#088141]/20 focus:border-[#088141] disabled:bg-slate-50 disabled:text-slate-400";

const primaryButtonClass =
  "w-full bg-gradient-to-r from-[#088141] to-[#0aa356] font-semibold text-white shadow-sm " +
  "hover:from-[#066d3a] hover:to-[#088141] focus-visible:ring-2 focus-visible:ring-[#088141]/30 " +
  "disabled:opacity-50 disabled:shadow-none";

export default function EmployeePortal() {
  const { t } = useTranslation("views/employeePortal");
  const [session, setSession] = useState<EmployeeSession>();
  const [options, setOptions] = useState<EmployeeAccessOption[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [camera, setCamera] = useState("");
  const [controller, setController] = useState("");
  const [door, setDoor] = useState("");
  const [selecting, setSelecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [countdown, setCountdown] = useState(10);
  const [result, setResult] = useState<EmployeeAccessResult>();
  const [error, setError] = useState("");
  const [optionsLoading, setOptionsLoading] = useState(false);

  useEffect(() => { document.title = t("title"); }, [t]);

  const refreshSession = useCallback(async () => {
    try {
      const current = await portalRequest<EmployeeSession>("session");
      setSession(current);
      if (!current.authenticated) {
        setOptions([]);
        setSelecting(false);
      }
    } catch {
      setError("service_unavailable");
    }
  }, []);

  useEffect(() => {
    void refreshSession();
    const timer = window.setInterval(() => { void refreshSession(); }, 5000);
    return () => window.clearInterval(timer);
  }, [refreshSession]);

  useEffect(() => {
    if (!session?.authenticated) return;
    let canceled = false;
    setOptionsLoading(true);
    portalRequest<EmployeeAccessOption[]>("options")
      .then((values) => { if (!canceled) setOptions(values); })
      .catch((failure: unknown) => {
        if (!canceled) setError(failure instanceof PortalError ? failure.reason : "service_unavailable");
      })
      .finally(() => { if (!canceled) setOptionsLoading(false); });
    return () => { canceled = true; };
  }, [session?.authenticated, selecting]);

  async function login(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      await portalRequest("login", session.csrf_token, { username, password });
      setPassword("");
      await refreshSession();
    } catch (failure) {
      setError(failure instanceof PortalError ? failure.reason : "service_unavailable");
    } finally { setBusy(false); }
  }

  async function logout() {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      await portalRequest("logout", session.csrf_token, {});
      setSelecting(false);
      setResult(undefined);
      setCamera(""); setController(""); setDoor("");
      await refreshSession();
    } catch (failure) {
      setError(failure instanceof PortalError ? failure.reason : "service_unavailable");
    } finally { setBusy(false); }
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    if (!session || busy || !camera || !controller || !door) return;
    setBusy(true);
    setVerifying(true);
    setError("");
    setResult(undefined);
    setCountdown(10);
    const started = Date.now();
    const timer = window.setInterval(() => setCountdown(Math.max(0, 10 - Math.floor((Date.now() - started) / 1000))), 250);
    try {
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;
      const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
      const requestId = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
      setResult(await portalRequest<EmployeeAccessResult>("forgot-card", session.csrf_token, {
        camera, controller_id: controller, door_id: door, request_id: requestId,
      }));
    } catch (failure) {
      setError(failure instanceof PortalError ? failure.reason : "connection_lost");
      if (failure instanceof PortalError && failure.status === 401) await refreshSession();
    } finally {
      window.clearInterval(timer);
      setVerifying(false);
      setBusy(false);
    }
  }

  const cameras = Array.from(new Set(options.map((option) => option.camera)));
  const controllers = options.filter((option) => option.camera === camera);
  const doors = controllers.find((option) => option.controller_id === controller)?.doors ?? [];
  const available = session?.enabled && session?.has_face;

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center bg-gradient-to-b from-slate-50 via-white to-slate-100 p-4">
      <section className="w-full max-w-md space-y-8">
        {/* ---------- Brand header ---------- */}
        <header className="flex flex-col items-center space-y-4 pt-4 text-center">
          <img
            src="/images/android-chrome-512x512.png"
            alt="Algérie Telecom"
            className="h-16 w-auto drop-shadow-sm"
          />
          <div className="space-y-1">
            <h1 className="text-3xl font-bold tracking-tight text-[#1F2359]">{t("title")}</h1>
            <p className="text-sm font-medium text-slate-500">Employee Access Portal</p>
          </div>
        </header>

        {/* ---------- Card ---------- */}
        <div className="space-y-6 rounded-2xl border border-slate-200 bg-white p-6 shadow-xl shadow-slate-900/5 sm:p-8">
          {/* Session loading */}
          {!session && (
            <div className="flex items-center justify-center gap-3 py-10">
              <Loader className="h-5 w-5 animate-spin text-[#088141]" />
              <p className="text-sm text-slate-500">{t("loading")}</p>
            </div>
          )}

          {/* Global error */}
          {error && (
            <div
              role="alert"
              className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"
            >
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
              <p>{t(`errors.${error}`, { defaultValue: t("errors.verification_failed") })}</p>
            </div>
          )}

          {/* ---------- Login ---------- */}
          {session && !session.authenticated && (
            <form onSubmit={login} className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="username" className="text-sm font-medium text-slate-700">
                  {t("username")}
                </Label>
                <Input
                  id="username"
                  autoComplete="username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  required
                  disabled={busy}
                  maxLength={64}
                  className={inputClass}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="password" className="text-sm font-medium text-slate-700">
                  {t("password")}
                </Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  disabled={busy}
                  maxLength={1024}
                  className={inputClass}
                />
              </div>

              <Button type="submit" className={primaryButtonClass} disabled={busy}>
                {busy ? `${t("signingIn")}…` : t("login")}
              </Button>
            </form>
          )}

          {/* ---------- Authenticated ---------- */}
          {session?.authenticated && (
            <div className="space-y-6">
              <div className="flex items-center justify-between gap-4 border-b border-slate-200 pb-4">
                <p className="truncate text-lg font-semibold text-[#1F2359]">
                  {t("welcome", { name: session.name })}
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void logout()}
                  disabled={busy}
                  className="shrink-0 text-slate-500 hover:bg-red-50 hover:text-red-600"
                >
                  <LogOut className="mr-2 h-4 w-4" />
                  {t("logout")}
                </Button>
              </div>

              {!session.enabled && (
                <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                  <p>{t("errors.system_disabled")}</p>
                </div>
              )}
              {!session.has_face && (
                <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                  <p>{t("errors.no_registered_face")}</p>
                </div>
              )}

              <Button
                className={`${primaryButtonClass} flex items-center justify-center gap-2`}
                disabled={!available || busy || selecting}
                onClick={() => { setSelecting(true); setResult(undefined); setError(""); }}
              >
                <Lock className="h-5 w-5" />
                {t("forgotCard")}
              </Button>

              {/* ---------- Verification form ---------- */}
              {selecting && available && (
                <form onSubmit={verify} className="space-y-6 border-t border-slate-200 pt-6">
                  <p className="text-sm font-semibold text-[#1F2359]">{t("instructions")}</p>

                  {optionsLoading && (
                    <div className="flex items-center justify-center gap-3 py-4">
                      <Loader className="h-4 w-4 animate-spin text-[#088141]" />
                      <p className="text-sm text-slate-500">{t("loading")}</p>
                    </div>
                  )}

                  {!optionsLoading && options.length === 0 && (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                      {t("noDoors")}
                    </div>
                  )}

                  {!optionsLoading && options.length > 0 && (
                    <>
                      <div className="space-y-2">
                        <Label className="flex items-center gap-2 text-sm font-medium text-slate-700">
                          <Camera className="h-4 w-4 text-[#088141]" />
                          {t("camera")}
                        </Label>
                        <Select
                          value={camera}
                          onValueChange={(value) => { setCamera(value); setController(""); setDoor(""); setResult(undefined); }}
                          disabled={busy}
                        >
                          <SelectTrigger aria-label={t("camera")} className={triggerClass}>
                            <SelectValue placeholder={t("selectCamera")} />
                          </SelectTrigger>
                          <SelectContent>
                            {cameras.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}
                          </SelectContent>
                        </Select>
                      </div>

                      <div className="space-y-2">
                        <Label className="text-sm font-medium text-slate-700">{t("controller")}</Label>
                        <Select
                          value={controller}
                          onValueChange={(value) => { setController(value); setDoor(""); setResult(undefined); }}
                          disabled={busy || !camera}
                        >
                          <SelectTrigger aria-label={t("controller")} className={triggerClass}>
                            <SelectValue placeholder={t("selectController")} />
                          </SelectTrigger>
                          <SelectContent>
                            {controllers.map((option) => (
                              <SelectItem key={option.controller_id} value={option.controller_id}>
                                {option.controller_name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      <div className="space-y-2">
                        <Label className="text-sm font-medium text-slate-700">{t("door")}</Label>
                        <Select
                          value={door}
                          onValueChange={(value) => { setDoor(value); setResult(undefined); }}
                          disabled={busy || !controller}
                        >
                          <SelectTrigger aria-label={t("door")} className={triggerClass}>
                            <SelectValue placeholder={t("selectDoor")} />
                          </SelectTrigger>
                          <SelectContent>
                            {doors.map((option) => (
                              <SelectItem key={option.id} value={option.id}>{option.name}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      {camera && (
                        <div className="space-y-3 rounded-xl border border-[#088141]/20 bg-[#088141]/5 p-4">
                          <div className="flex items-start gap-3">
                            <Camera className="mt-0.5 h-5 w-5 shrink-0 animate-pulse text-[#088141]" />
                            <p className="text-sm text-slate-700">{t("faceCamera", { camera })}</p>
                          </div>
                          <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-[#088141]/30 bg-white">
                            <div className="space-y-2 text-center">
                              <Camera className="mx-auto h-8 w-8 animate-bounce text-[#088141]" />
                              <p className="text-xs text-slate-400">Face the camera directly</p>
                            </div>
                          </div>
                        </div>
                      )}

                      <Button
                        type="submit"
                        className={primaryButtonClass}
                        disabled={busy || !doors.some((option) => option.id === door)}
                      >
                        {t("verify")}
                      </Button>
                    </>
                  )}
                </form>
              )}

              {/* ---------- Verifying progress ---------- */}
              {verifying && (
                <div className="space-y-3 rounded-xl border border-[#088141]/20 bg-[#088141]/5 p-4">
                  <div className="flex items-center justify-center gap-2">
                    <Loader className="h-5 w-5 animate-spin text-[#088141]" />
                    <p className="font-semibold text-[#1F2359]">
                      {countdown > 0 ? t("verifying", { seconds: countdown }) : t("finalizing")}
                    </p>
                  </div>
                  <div className="h-1 overflow-hidden rounded-full bg-slate-200">
                    <div
                      className="h-full bg-gradient-to-r from-[#088141] to-[#0aa356] transition-[width] duration-200 ease-linear"
                      style={{ width: `${Math.max(0, countdown * 10)}%` }}
                    />
                  </div>
                </div>
              )}

              {/* ---------- Result ---------- */}
              {result && (
                <div
                  role={result.success ? "status" : "alert"}
                  className={`space-y-3 rounded-xl border p-4 ${
                    result.success
                      ? "border-emerald-200 bg-emerald-50"
                      : "border-red-200 bg-red-50"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    {result.success ? (
                      <CheckCircle className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
                    ) : (
                      <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
                    )}

                    {result.success ? (
                      <div className="space-y-1 text-sm text-emerald-800">
                        <p className="font-semibold">{t("verified")}</p>
                        <p>{t("continue")}</p>
                        <p className="font-semibold text-emerald-700">{t("unlockRequested")}</p>
                      </div>
                    ) : (
                      <div className="space-y-1 text-sm text-red-700">
                        {result.identity_verified && (
                          <p className="text-amber-700">{t("verified")}</p>
                        )}
                        <p className="font-semibold">
                          {t(`errors.${result.reason}`, { defaultValue: t("errors.verification_failed") })}
                        </p>
                      </div>
                    )}
                  </div>

                  {!result.success && (
                    <Button
                      variant="outline"
                      onClick={() => { setResult(undefined); setError(""); setSelecting(true); }}
                      className="w-full border-slate-300 text-slate-700 hover:bg-slate-50 hover:text-slate-900"
                    >
                      {t("verify")}
                    </Button>
                  )}
                </div>
              )}

              {/* ---------- Cancel ---------- */}
              {selecting && (
                <Button
                  variant="outline"
                  onClick={() => { setSelecting(false); setResult(undefined); setError(""); }}
                  disabled={busy}
                  className="w-full border-slate-300 text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                >
                  Cancel
                </Button>
              )}
            </div>
          )}
        </div>

        {/* ---------- Footer ---------- */}
        <footer className="pb-4 text-center text-xs text-slate-400">
          <p>Secured Access Portal © 2026</p>
        </footer>
      </section>
    </main>
  );
}
