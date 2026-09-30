import axios from "axios";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import useSWR from "swr";
import { baseUrl } from "@/api/baseUrl";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import ImageEntry from "@/components/input/ImageEntry";
import type { EmployeeAuditRecord, EmployeeRecord, EmployeeSettings } from "@/types/employee";
import type { FaceLibraryData } from "@/types/face";

type Controller = { id: string; name: string; associated_camera: string | null };
type Door = { id: string; name: string };
type AccountForm = { employee: EmployeeRecord | null; name: string; username: string; password: string; enabled: boolean };

export default function Employees() {
  const { t } = useTranslation("views/employees");
  const { data: employees, mutate: refreshEmployees, error: employeesError } = useSWR<EmployeeRecord[]>("employees", { refreshInterval: 15000 });
  const { data: settings, mutate: refreshSettings } = useSWR<EmployeeSettings>("employee-access/settings", { refreshInterval: 5000 });
  const { data: controllers } = useSWR<Controller[]>("access-controllers");
  const { data: faces, mutate: refreshFaces } = useSWR<FaceLibraryData>("faces");
  const { data: audit, mutate: refreshAudit } = useSWR<EmployeeAuditRecord[]>("employee-access/audit", { refreshInterval: 15000 });
  const [search, setSearch] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState<AccountForm | null>(null);
  const [passwordTarget, setPasswordTarget] = useState<EmployeeRecord | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<EmployeeRecord | null>(null);
  const [uploadTarget, setUploadTarget] = useState<EmployeeRecord | null>(null);
  const [faceTarget, setFaceTarget] = useState<EmployeeRecord | null>(null);
  const [selectedFace, setSelectedFace] = useState("");
  const [renameFace, setRenameFace] = useState(false);
  const [permissionTarget, setPermissionTarget] = useState<EmployeeRecord | null>(null);
  const [selectedController, setSelectedController] = useState("");
  const [checkedDoors, setCheckedDoors] = useState<string[]>([]);
  const [linkTarget, setLinkTarget] = useState<EmployeeRecord | null>(null);
  const [survivor, setSurvivor] = useState("");
  const { data: doorResponse, error: doorsError, isLoading: doorsLoading } = useSWR<{ doors: Door[] }>(
    permissionTarget && selectedController ? `access-controllers/${selectedController}/doors` : null,
  );

  useEffect(() => { document.title = t("title"); }, [t]);
  useEffect(() => {
    setCheckedDoors(permissionTarget?.permissions.find((permission) => permission.controller_id === selectedController)?.doors ?? []);
  }, [permissionTarget, selectedController]);

  const portalUrl = useMemo(() => {
    const url = new URL(baseUrl);
    url.port = String(settings?.port ?? 8972);
    url.pathname = "/"; url.search = ""; url.hash = "";
    return url.toString();
  }, [settings?.port]);
  const filtered = employees?.filter((employee) => `${employee.display_name} ${employee.username ?? ""}`.toLocaleLowerCase().includes(search.toLocaleLowerCase())) ?? [];
  const existingFaces = Object.keys(faces ?? {}).filter((name) => name !== "train" && faces?.[name]?.length).sort();
  const controllerName = (id: string) => controllers?.find((controller) => controller.id === id)?.name ?? id;

  async function act(action: () => Promise<unknown>): Promise<boolean> {
    setWorking(true); setError("");
    try {
      await action();
      await Promise.all([refreshEmployees(), refreshSettings(), refreshFaces(), refreshAudit()]);
      return true;
    } catch (failure) {
      const reason = axios.isAxiosError<{ reason?: string }>(failure) ? failure.response?.data.reason : undefined;
      setError(reason ?? "save_failed");
      return false;
    } finally { setWorking(false); }
  }

  async function saveAccount(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    const body = { name: form.name, username: form.username, password: form.password || null, enabled: form.enabled };
    const saved = await act(() => form.employee ? axios.put(`employees/${form.employee.id}`, body) : axios.post("employees", body));
    if (saved) setForm(null);
  }

  function edit(employee: EmployeeRecord | null) {
    setError("");
    setForm({ employee, name: employee?.name ?? employee?.display_name ?? "", username: employee?.username ?? "", password: "", enabled: employee?.enabled ?? true });
  }

  return (
    <main className="size-full space-y-6 overflow-y-auto p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline"><a href={portalUrl} target="_blank" rel="noopener noreferrer">{t("openPortal")}</a></Button>
          <Button variant="outline" disabled={working} onClick={() => void act(() => axios.post("employee-access/sync"))}>{t("sync")}</Button>
          <Button disabled={working} onClick={() => edit(null)}>{t("create")}</Button>
        </div>
      </div>
      <div className="flex items-center gap-3 rounded-lg border border-secondary-highlight p-4">
        <Switch id="cardless-enabled" checked={settings?.enabled ?? false} disabled={!settings || working}
          onCheckedChange={(enabled) => void act(() => axios.put("employee-access/settings", { enabled }))} />
        <div><Label htmlFor="cardless-enabled">{t("systemEnabled")}</Label><p className="text-sm text-secondary-foreground">{t("localOnly")}</p></div>
      </div>
      {error && <p role="alert" className="text-danger">{t(`errors.${error}`, { defaultValue: t("errors.save_failed") })}</p>}
      {employeesError && <p role="alert" className="text-danger">{t("loadFailed")}</p>}
      <Input aria-label={t("search")} placeholder={t("search")} value={search} onChange={(event) => setSearch(event.target.value)} />
      {!employees && !employeesError && <p role="status">{t("loading")}</p>}
      {employees && filtered.length === 0 && <p>{t("empty")}</p>}
      <Table>
        <TableHeader><TableRow><TableHead>{t("name")}</TableHead><TableHead>{t("username")}</TableHead><TableHead>{t("status")}</TableHead><TableHead>{t("face")}</TableHead><TableHead>{t("doors")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
        <TableBody>{filtered.map((employee) => (
          <TableRow key={employee.id}>
            <TableCell><p className="font-medium">{employee.display_name}</p>{employee.sources.map((source) => <p className="text-xs text-secondary-foreground" key={source.id}>{controllerName(source.controller_id)}: {source.user_id}</p>)}</TableCell>
            <TableCell>{employee.username ?? t("notAssigned")}</TableCell>
            <TableCell>{t(!employee.enabled ? "disabled" : employee.pending ? "pending" : "active")}</TableCell>
            <TableCell>{t(employee.has_face ? "registered" : "notRegistered")}</TableCell>
            <TableCell>{employee.permissions.length ? employee.permissions.map((permission) => <p key={permission.controller_id}>{t("doorCount", { controller: controllerName(permission.controller_id), count: permission.doors.length })}</p>) : t("none")}</TableCell>
            <TableCell><div className="flex max-w-xl flex-wrap gap-2">
              <Button size="sm" variant="outline" disabled={working} onClick={() => edit(employee)}>{t("edit")}</Button>
              <Button size="sm" variant="outline" disabled={working} onClick={() => void act(() => axios.put(`employees/${employee.id}/enabled`, { enabled: !employee.enabled }))}>{t(employee.enabled ? "disable" : "enable")}</Button>
              <Button size="sm" variant="outline" disabled={working} onClick={() => { setNewPassword(""); setPasswordTarget(employee); }}>{t("changePassword")}</Button>
              <Button size="sm" variant="outline" disabled={working || !employee.name} onClick={() => setUploadTarget(employee)}>{t("uploadFace")}</Button>
              <Button size="sm" variant="outline" disabled={working || !employee.name} onClick={() => { setSelectedFace(employee.face_name ?? ""); setRenameFace(false); setFaceTarget(employee); }}>{t("existingFace")}</Button>
              <Button size="sm" variant="outline" disabled={working} onClick={() => { setSelectedController(employee.permissions[0]?.controller_id ?? controllers?.[0]?.id ?? ""); setPermissionTarget(employee); }}>{t("assignDoors")}</Button>
              <Button size="sm" variant="outline" disabled={working || employee.sources.length === 0} onClick={() => { setSurvivor(""); setLinkTarget(employee); }}>{t("linkRecords")}</Button>
              <Button size="sm" variant="destructive" disabled={working} onClick={() => setDeleteTarget(employee)}>{t("delete")}</Button>
            </div></TableCell>
          </TableRow>
        ))}</TableBody>
      </Table>
      <section className="space-y-3"><h2 className="text-lg font-semibold">{t("syncHealth")}</h2>
        <p className="text-sm text-secondary-foreground">{t("importHelp")}</p>
        {settings?.sync.map((sync) => <p key={sync.controller_id}>{controllerName(sync.controller_id)}: {t(`syncStatus.${sync.status}`)}</p>)}
      </section>
      <section className="space-y-3"><h2 className="text-lg font-semibold">{t("audit")}</h2>
        <Table><TableHeader><TableRow><TableHead>{t("time")}</TableHead><TableHead>{t("name")}</TableHead><TableHead>{t("camera")}</TableHead><TableHead>{t("doors")}</TableHead><TableHead>{t("result")}</TableHead></TableRow></TableHeader>
          <TableBody>{audit?.map((entry) => <TableRow key={entry.id}>
            <TableCell>{new Date(entry.created_at * 1000).toLocaleString()}</TableCell>
            <TableCell>{employees?.find((employee) => employee.id === entry.employee_id)?.display_name ?? t("deletedEmployee")}</TableCell>
            <TableCell>{entry.camera}</TableCell><TableCell>{controllerName(entry.controller_id)}: {entry.door_id}</TableCell>
            <TableCell>{entry.result.reason ? t(`errors.${entry.result.reason}`, { defaultValue: t("errors.verification_failed") }) : t("inProgress")}</TableCell>
          </TableRow>)}</TableBody>
        </Table>
      </section>

      <Dialog open={form !== null} onOpenChange={(open) => { if (!open) setForm(null); }}><DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader><DialogTitle>{t(form?.employee ? "edit" : "create")}</DialogTitle><DialogDescription>{t("accountHelp")}</DialogDescription></DialogHeader>
        {form && <form onSubmit={saveAccount} className="space-y-4">
          <div className="space-y-2"><Label htmlFor="employee-name">{t("name")}</Label><Input id="employee-name" value={form.name} maxLength={50} required onChange={(event) => setForm({ ...form, name: event.target.value })} /></div>
          <div className="space-y-2"><Label htmlFor="employee-username">{t("username")}</Label><Input id="employee-username" value={form.username} autoComplete="off" minLength={3} maxLength={64} required onChange={(event) => setForm({ ...form, username: event.target.value })} /></div>
          <div className="space-y-2"><Label htmlFor="employee-password">{t("password")}</Label><Input id="employee-password" type="password" autoComplete="new-password" value={form.password} minLength={12} maxLength={1024} required={!form.employee || form.employee.pending} onChange={(event) => setForm({ ...form, password: event.target.value })} /><p className="text-sm text-secondary-foreground">{t("passwordHelp")}</p></div>
          <div className="flex items-center gap-2"><Switch id="employee-enabled" checked={form.enabled} onCheckedChange={(enabled) => setForm({ ...form, enabled })} /><Label htmlFor="employee-enabled">{t("enabled")}</Label></div>
          {error && <p role="alert" className="text-danger">{t(`errors.${error}`, { defaultValue: t("errors.save_failed") })}</p>}
          <DialogFooter><Button type="button" variant="outline" disabled={working} onClick={() => setForm(null)}>{t("cancel")}</Button><Button type="submit" disabled={working}>{t("save")}</Button></DialogFooter>
        </form>}
      </DialogContent></Dialog>

      <Dialog open={passwordTarget !== null} onOpenChange={(open) => { if (!open) { setPasswordTarget(null); setNewPassword(""); } }}><DialogContent>
        <DialogHeader><DialogTitle>{t("changePassword")}</DialogTitle><DialogDescription>{t("passwordHelp")}</DialogDescription></DialogHeader>
        <form className="space-y-4" onSubmit={async (event) => { event.preventDefault(); if (passwordTarget && await act(() => axios.put(`employees/${passwordTarget.id}/password`, { password: newPassword }))) { setPasswordTarget(null); setNewPassword(""); } }}>
          <Label htmlFor="new-password">{t("password")}</Label><Input id="new-password" type="password" autoComplete="new-password" value={newPassword} minLength={12} maxLength={1024} required onChange={(event) => setNewPassword(event.target.value)} />
          {error && <p role="alert" className="text-danger">{t(`errors.${error}`, { defaultValue: t("errors.save_failed") })}</p>}
          <DialogFooter><Button type="submit" disabled={working}>{t("save")}</Button></DialogFooter>
        </form>
      </DialogContent></Dialog>

      <Dialog open={uploadTarget !== null} onOpenChange={(open) => { if (!open && !working) setUploadTarget(null); }}><DialogContent>
        <DialogHeader><DialogTitle>{t("uploadFace")}</DialogTitle><DialogDescription>{t("faceHelp")}</DialogDescription></DialogHeader>
        {error && <p role="alert" className="text-danger">{t(`errors.${error}`, { defaultValue: t("errors.save_failed") })}</p>}
        <ImageEntry maxSize={10 * 1024 * 1024} onSave={(file) => {
          if (!uploadTarget || working) return;
          const data = new FormData(); data.append("file", file);
          void act(() => axios.post(`employees/${uploadTarget.id}/face`, data)).then((saved) => { if (saved) setUploadTarget(null); });
        }}><DialogFooter><Button type="button" variant="outline" disabled={working} onClick={() => setUploadTarget(null)}>{t("cancel")}</Button>
          <Button type="submit" disabled={working}>{t("save")}</Button></DialogFooter>
        </ImageEntry>
      </DialogContent></Dialog>

      <Dialog open={faceTarget !== null} onOpenChange={(open) => { if (!open) setFaceTarget(null); }}><DialogContent>
        <DialogHeader><DialogTitle>{t("existingFace")}</DialogTitle><DialogDescription>{t("faceHelp")}</DialogDescription></DialogHeader>
        <Select value={selectedFace} onValueChange={setSelectedFace}><SelectTrigger aria-label={t("face")}><SelectValue placeholder={t("selectFace")} /></SelectTrigger>
          <SelectContent>{existingFaces.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent></Select>
        {selectedFace && selectedFace !== faceTarget?.name && <div className="flex items-center gap-2"><Checkbox id="rename-face" checked={renameFace} onCheckedChange={(checked) => setRenameFace(checked === true)} /><Label htmlFor="rename-face">{t("renameFace", { name: faceTarget?.name })}</Label></div>}
        {error && <p role="alert" className="text-danger">{t(`errors.${error}`, { defaultValue: t("errors.save_failed") })}</p>}
        <DialogFooter><Button disabled={working || !selectedFace || (selectedFace !== faceTarget?.name && !renameFace)} onClick={async () => {
          if (faceTarget && await act(() => axios.put(`employees/${faceTarget.id}/face`, { face_name: selectedFace, rename: renameFace }))) setFaceTarget(null);
        }}>{t("save")}</Button></DialogFooter>
      </DialogContent></Dialog>

      <Dialog open={permissionTarget !== null} onOpenChange={(open) => { if (!open) setPermissionTarget(null); }}><DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader><DialogTitle>{t("assignDoors")}</DialogTitle><DialogDescription>{t("permissionsHelp")}</DialogDescription></DialogHeader>
        <Select value={selectedController} onValueChange={setSelectedController}><SelectTrigger aria-label={t("controller")}><SelectValue placeholder={t("selectController")} /></SelectTrigger>
          <SelectContent>{controllers?.map((controller) => <SelectItem key={controller.id} value={controller.id}>{controller.name}</SelectItem>)}</SelectContent></Select>
        <p>{t(permissionTarget?.permissions.find((permission) => permission.controller_id === selectedController)?.overridden ? "localOverride" : "importedPermissions")}</p>
        {doorsLoading && <p role="status">{t("loading")}</p>}{doorsError && <p role="alert" className="text-danger">{t("errors.controller_unavailable")}</p>}
        {doorResponse?.doors.map((door) => <div className="flex items-center gap-2" key={door.id}><Checkbox id={`door-${door.id}`} checked={checkedDoors.includes(door.id)} disabled={working} onCheckedChange={(checked) => setCheckedDoors((current) => checked === true ? [...current, door.id] : current.filter((id) => id !== door.id))} /><Label htmlFor={`door-${door.id}`}>{door.name}</Label></div>)}
        {error && <p role="alert" className="text-danger">{t(`errors.${error}`, { defaultValue: t("errors.save_failed") })}</p>}
        <DialogFooter>
          <Button variant="outline" disabled={working || !selectedController} onClick={async () => { if (permissionTarget && await act(() => axios.delete(`employees/${permissionTarget.id}/controllers/${selectedController}/doors`))) setPermissionTarget(null); }}>{t("restorePermissions")}</Button>
          <Button disabled={working || !doorResponse || !!doorsError || doorsLoading} onClick={async () => { if (permissionTarget && await act(() => axios.put(`employees/${permissionTarget.id}/controllers/${selectedController}/doors`, { doors: checkedDoors.filter((id) => doorResponse?.doors.some((door) => door.id === id)) }))) setPermissionTarget(null); }}>{t("save")}</Button>
        </DialogFooter>
      </DialogContent></Dialog>

      <Dialog open={linkTarget !== null} onOpenChange={(open) => { if (!open) setLinkTarget(null); }}><DialogContent>
        <DialogHeader><DialogTitle>{t("linkRecords")}</DialogTitle><DialogDescription>{t("linkHelp")}</DialogDescription></DialogHeader>
        <Select value={survivor} onValueChange={setSurvivor}><SelectTrigger aria-label={t("survivingEmployee")}><SelectValue placeholder={t("survivingEmployee")} /></SelectTrigger>
          <SelectContent>{employees?.filter((employee) => employee.id !== linkTarget?.id).map((employee) => <SelectItem key={employee.id} value={employee.id}>{employee.display_name} ({employee.username ?? employee.id})</SelectItem>)}</SelectContent></Select>
        {error && <p role="alert" className="text-danger">{t(`errors.${error}`, { defaultValue: t("errors.save_failed") })}</p>}
        <DialogFooter><Button disabled={!survivor || working} onClick={async () => { if (linkTarget && await act(() => axios.post(`employees/${survivor}/sources`, { source_ids: linkTarget.sources.map((source) => source.id) }))) setLinkTarget(null); }}>{t("confirmLink")}</Button></DialogFooter>
      </DialogContent></Dialog>

      <AlertDialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}><AlertDialogContent>
        <AlertDialogHeader><AlertDialogTitle>{t("delete")}</AlertDialogTitle><AlertDialogDescription>{t("deleteHelp", { name: deleteTarget?.display_name })}</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>{t("cancel")}</AlertDialogCancel><AlertDialogAction disabled={working} onClick={() => { if (deleteTarget) void act(() => axios.delete(`employees/${deleteTarget.id}`)); }}>{t("delete")}</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent></AlertDialog>
    </main>
  );
}
