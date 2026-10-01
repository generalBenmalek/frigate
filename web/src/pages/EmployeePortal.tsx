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
    <main className="flex min-h-dvh flex-col items-center justify-center bg-gradient-to-b from-white to-gray-50 p-4">
      <section className="w-full max-w-md space-y-8">
        <div className="flex flex-col items-center justify-center space-y-4 pt-4">
          <img src="/images/algerie-telecom-seeklogo.png" alt="Algerie Telecom" className="h-16 w-auto drop-shadow-lg" />
          <div className="space-y-2 text-center">
            <h1 className="text-3xl font-bold text-[#1F2359]">{t("title")}</h1>
            <p className="text-sm text-blue-900">Employee Access Portal</p>
          </div>
        </div>

        <div className="space-y-6 rounded-xl border border-[#088141]/30 bg-blue-50/80 p-8 shadow-2xl backdrop-blur-sm">
          {!session && <div className="flex items-center justify-center space-x-2 py-8">
            <Loader className="h-5 w-5 animate-spin text-[#088141]" />
            <p className="text-white/70">{t("loading")}</p>
          </div>}
          
          {error && <div role="alert" className="flex items-start gap-3 rounded-lg bg-red-500/20 p-4 text-red-100 border border-red-500/30">
            <AlertCircle className="h-5 w-5 flex-shrink-0 mt-0.5" />
            <p>{t(`errors.${error}`, { defaultValue: t("errors.verification_failed") })}</p>
          </div>}
          
          {session && !session.authenticated && (
            <form onSubmit={login} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="username" className="text-[#1F2359]">{t("username")}</Label>
                <Input 
                  id="username" 
                  autoComplete="username" 
                  value={username} 
                  onChange={(event) => setUsername(event.target.value)} 
                  required 
                  disabled={busy} 
                  maxLength={64}
                  className="bg-blue-50/80 border-[#1F2359]/20 text-white placeholder-white focus:border-[#088141] focus:ring-[#088141]/50" 
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password" className="text-[#1F2359]">{t("password")}</Label>
                <Input 
                  id="password" 
                  type="password" 
                  autoComplete="current-password" 
                  value={password} 
                  onChange={(event) => setPassword(event.target.value)} 
                  required 
                  disabled={busy} 
                  maxLength={1024}
                  className="bg-blue-50/80 border-[#1F2359]/20 text-white placeholder-white focus:border-[#088141] focus:ring-[#088141]/50"
                />
              </div>
              <Button 
                type="submit" 
                className="w-full bg-gradient-to-r from-[#088141] to-[#06a856] hover:from-[#066d3a] hover:to-[#077a42] text-white font-semibold py-2" 
                disabled={busy}
              >
                {busy ? `${t("signingIn")}...` : t("login")}
              </Button>
            </form>
          )}

          {session?.authenticated && (
            <div className="space-y-6">
              <div className="flex items-center justify-between gap-4 pb-4 border-b border-[#1F2359]/15">
                <p className="text-lg font-semibold text-[#1F2359]">{t("welcome", { name: session.name })}</p>
                <Button 
                  variant="ghost" 
                  size="sm"
                  onClick={() => void logout()} 
                  disabled={busy}
                  className="text-red-300 hover:text-red-100 hover:bg-red-500/20"
                >
                  <LogOut className="h-4 w-4 mr-2" />
                  {t("logout")}
                </Button>
              </div>

              {!session.enabled && <div className="rounded-lg bg-yellow-500/20 p-3 text-yellow-100 border border-yellow-500/30">
                <p>{t("errors.system_disabled")}</p>
              </div>}
              {!session.has_face && <div className="rounded-lg bg-yellow-500/20 p-3 text-yellow-100 border border-yellow-500/30">
                <p>{t("errors.no_registered_face")}</p>
              </div>}

              <Button 
                className="w-full bg-gradient-to-r from-[#088141] to-[#06a856] hover:from-[#066d3a] hover:to-[#077a42] text-white font-semibold py-2 flex items-center justify-center gap-2" 
                disabled={!available || busy || selecting} 
                onClick={() => { setSelecting(true); setResult(undefined); setError(""); }}
              >
                <Lock className="h-5 w-5" />
                {t("forgotCard")}
              </Button>

              {selecting && available && (
                <form onSubmit={verify} className="space-y-6 border-t border-[#1F2359]/15 pt-6">
                  <div className="space-y-2">
                    <p className="text-sm font-semibold text-blue-900">{t("instructions")}</p>
                  </div>

                  {optionsLoading && <div className="flex items-center justify-center space-x-2 py-4">
                    <Loader className="h-4 w-4 animate-spin text-[#088141]" />
                    <p className="text-white/70 text-sm">{t("loading")}</p>
                  </div>}

                  {!optionsLoading && options.length === 0 && <div className="rounded-lg bg-yellow-500/20 p-3 text-yellow-100">
                    <p className="text-sm">{t("noDoors")}</p>
                  </div>}

                  {!optionsLoading && options.length > 0 && (
                    <>
                      <div className="space-y-2">
                        <Label className="text-white font-medium flex items-center gap-2">
                          <Camera className="h-4 w-4 text-[#088141]" />
                          {t("camera")}
                        </Label>
                        <Select value={camera} onValueChange={(value) => { setCamera(value); setController(""); setDoor(""); setResult(undefined); }} disabled={busy}>
                          <SelectTrigger aria-label={t("camera")} className="bg-blue-50/80 border-[#1F2359]/20 text-[#1F2359]">
                            <SelectValue placeholder={t("selectCamera")} />
                          </SelectTrigger>
                          <SelectContent>{cameras.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent>
                        </Select>
                      </div>

                      <div className="space-y-2">
                        <Label className="text-white font-medium">{t("controller")}</Label>
                        <Select value={controller} onValueChange={(value) => { setController(value); setDoor(""); setResult(undefined); }} disabled={busy || !camera}>
                          <SelectTrigger aria-label={t("controller")} className="bg-blue-50/80 border-[#1F2359]/20 text-[#1F2359]">
                            <SelectValue placeholder={t("selectController")} />
                          </SelectTrigger>
                          <SelectContent>{controllers.map((option) => <SelectItem key={option.controller_id} value={option.controller_id}>{option.controller_name}</SelectItem>)}</SelectContent>
                        </Select>
                      </div>

                      <div className="space-y-2">
                        <Label className="text-white font-medium">{t("door")}</Label>
                        <Select value={door} onValueChange={(value) => { setDoor(value); setResult(undefined); }} disabled={busy || !controller}>
                          <SelectTrigger aria-label={t("door")} className="bg-blue-50/80 border-[#1F2359]/20 text-[#1F2359]">
                            <SelectValue placeholder={t("selectDoor")} />
                          </SelectTrigger>
                          <SelectContent>{doors.map((option) => <SelectItem key={option.id} value={option.id}>{option.name}</SelectItem>)}</SelectContent>
                        </Select>
                      </div>

                      {camera && (
                        <div className="space-y-3 rounded-lg bg-[#088141]/10 p-4 border border-[#1F2359]/20">
                          <div className="flex items-start gap-3">
                            <Camera className="h-5 w-5 text-[#088141] mt-0.5 flex-shrink-0 animate-pulse" />
                            <p className="text-sm text-[#1F2359]">{t("faceCamera", { camera })}</p>
                          </div>
                          <div className="flex items-center justify-center h-24 bg-white/5 rounded border border-[#1F2359]/15">
                            <div className="text-center space-y-2">
                              <Camera className="h-8 w-8 text-[#088141] mx-auto animate-bounce" />
                              <p className="text-xs text-blue-900">Face the camera directly</p>
                            </div>
                          </div>
                        </div>
                      )}

                      <Button 
                        type="submit" 
                        className="w-full bg-gradient-to-r from-[#088141] to-[#06a856] hover:from-[#066d3a] hover:to-[#077a42] text-white font-semibold py-2" 
                        disabled={busy || !doors.some((option) => option.id === door)}
                      >
                        {t("verify")}
                      </Button>
                    </>
                  )}
                </form>
              )}

              {verifying && (
                <div className="space-y-3 rounded-lg bg-[#088141]/10 p-4 border border-[#1F2359]/20">
                  <div className="flex items-center justify-center gap-2">
                    <Loader className="h-5 w-5 animate-spin text-[#088141]" />
                    <p className="text-white font-semibold">{countdown > 0 ? t("verifying", { seconds: countdown }) : t("finalizing")}</p>
                  </div>
                  <div className="h-1 bg-blue-400/20 rounded-full overflow-hidden">
                    <div className="h-full bg-gradient-to-r from-[#088141] to-[#06a856] animate-pulse" style={{ width: `${Math.max(0, countdown * 10)}%` }} />
                  </div>
                </div>
              )}

              {result && (
                <div role={result.success ? "status" : "alert"} className={`space-y-3 rounded-lg p-4 border ${result.success ? 'bg-green-500/20 border-green-400/30' : 'bg-red-500/20 border-red-400/30'}`}>
                  <div className="flex items-start gap-3">
                    {result.success ? (
                      <CheckCircle className="h-5 w-5 text-green-300 mt-0.5 flex-shrink-0" />
                    ) : (
                      <AlertCircle className="h-5 w-5 text-red-300 mt-0.5 flex-shrink-0" />
                    )}
                    <div className={result.success ? "text-green-100" : "text-red-100"}>
                      {result.success ? (
                        <div className="space-y-1">
                          <p className="font-semibold">{t("verified")}</p>
                          <p className="text-sm">{t("continue")}</p>
                          <p className="text-sm font-semibold text-green-200">{t("unlockRequested")}</p>
                        </div>
                      ) : (
                        <div className="space-y-1">
                          {result.identity_verified && <p className="text-sm text-yellow-200">{t("verified")}</p>}
                          <p className="font-semibold">{t(`errors.${result.reason}`, { defaultValue: t("errors.verification_failed") })}</p>
                        </div>
                      )}
                    </div>
                  </div>
                  {!result.success && (
                    <Button 
                      onClick={() => { setResult(undefined); setError(""); setSelecting(true); }}
                      className="w-full bg-blue-50/80 hover:bg-white/20 text-white border border-white/20"
                      variant="outline"
                    >
                      {t("verify")}
                    </Button>
                  )}
                </div>
              )}

              {selecting && (
                <Button 
                  onClick={() => { setSelecting(false); setResult(undefined); setError(""); }}
                  variant="outline"
                  className="w-full text-white border-[#1F2359]/20 hover:bg-[#088141]/10"
                  disabled={busy}
                >
                  Cancel
                </Button>
              )}
            </div>
          )}
        </div>

        <div className="text-center text-xs text-blue-800/60 pb-4">
          <p>Secured Access Portal � 2026</p>
        </div>
      </section>
    </main>
  );
}


