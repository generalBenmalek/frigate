import axios from "axios";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import useSWR from "swr";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LuPencil, LuPlus, LuRotateCcw, LuTrash2 } from "react-icons/lu";

type AccessControllerRecord = {
  id: string;
  name: string;
  ip_address: string;
  port: number;
  type: string;
  model: string;
  serial_number: string;
  status: string;
  associated_camera?: string | null;
  username?: string;
  password?: string;
};

type EventRecord = {
  device_id?: string;
  device_name?: string;
  time?: string;
  Time?: string;
  timestamp?: string;
  Code?: string;
  code?: string;
  action?: string;
  data?: Record<string, unknown> | string | null;
  [key: string]: unknown;
};

type DeviceFormValues = {
  id: string;
  name: string;
  username: string;
  password: string;
  ipAddress: string;
  port: number;
};

type DeviceEditorState = {
  mode: "create" | "edit";
  device: AccessControllerRecord | null;
};

function getErrorMessage(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    return (
      (error.response?.data as { message?: string; detail?: string } | undefined)
        ?.message ??
      (error.response?.data as { message?: string; detail?: string } | undefined)
        ?.detail ??
      error.message ??
      fallback
    );
  }

  return fallback;
}

export default function AccessControllerPage() {
  const { t } = useTranslation(["common", "views/organization"]);
  const [activeTab, setActiveTab] = useState<"controllers" | "events">("controllers");
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("all");
  const [deviceEditor, setDeviceEditor] = useState<DeviceEditorState | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  useEffect(() => {
    document.title = t("documentTitle", { ns: "views/organization" });
  }, [t]);

  const {
    data: controllers,
    mutate: refreshControllers,
    error: controllersError,
  } = useSWR<AccessControllerRecord[]>("access-controllers", {
    revalidateOnFocus: false,
  });

  const eventKey = useMemo(
    () =>
      selectedDeviceId === "all"
        ? "access-controllers/events"
        : `access-controllers/events?device_id=${encodeURIComponent(selectedDeviceId)}`,
    [selectedDeviceId],
  );

  const {
    data: events,
    mutate: refreshEvents,
    error: eventsError,
  } = useSWR<EventRecord[]>(eventKey, {
    revalidateOnFocus: false,
    refreshInterval: 5000,
  });

  useEffect(() => {
    if (controllersError) {
      toast.error(
        getErrorMessage(
          controllersError,
          t("toast.error.loadDevicesFailed", { ns: "views/organization" }),
        ),
        { position: "top-center" },
      );
    }
  }, [controllersError, t]);

  useEffect(() => {
    if (eventsError) {
      toast.error(
        getErrorMessage(
          eventsError,
          t("toast.error.loadEventsFailed", { ns: "views/organization" }),
        ),
        { position: "top-center" },
      );
    }
  }, [eventsError, t]);

  const deviceList = controllers ?? [];
  const eventList = events ?? [];

  const handleSave = async (values: DeviceFormValues, mode: "create" | "edit") => {
    const payload = {
      id: values.id,
      name: values.name,
      username: values.username,
      password: values.password,
      ip_address: values.ipAddress,
      port: values.port,
    };

    try {
      if (mode === "create") {
        await axios.post("access-controllers", payload);
        toast.success(t("toast.success.created", { ns: "views/organization" }), {
          position: "top-center",
        });
      } else {
        await axios.put(`access-controllers/${values.id}`, payload);
        toast.success(t("toast.success.updated", { ns: "views/organization" }), {
          position: "top-center",
        });
      }

      await Promise.all([refreshControllers(), refreshEvents()]);
      setDeviceEditor(null);
    } catch (error) {
      toast.error(
        getErrorMessage(error, t("toast.error.saveFailed", { ns: "views/organization" })),
        { position: "top-center" },
      );
      throw error;
    }
  };

  const handleRetry = async (deviceId: string) => {
    try {
      await axios.post(`access-controllers/${deviceId}/refresh`);
      toast.success(t("toast.success.refreshed", { ns: "views/organization" }), {
        position: "top-center",
      });
      await refreshControllers();
    } catch (error) {
      toast.error(
        getErrorMessage(error, t("toast.error.refreshFailed", { ns: "views/organization" })),
        { position: "top-center" },
      );
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) {
      return;
    }

    try {
      await axios.delete(`access-controllers/${deleteTarget.id}`);
      toast.success(t("toast.success.deleted", { ns: "views/organization" }), {
        position: "top-center",
      });
      await refreshControllers();
      setDeleteTarget(null);
    } catch (error) {
      toast.error(
        getErrorMessage(error, t("toast.error.deleteFailed", { ns: "views/organization" })),
        { position: "top-center" },
      );
    }
  };

  const statusClasses: Record<string, string> = {
    online: "bg-emerald-500/10 text-emerald-500",
    offline: "bg-red-500/10 text-red-500",
    error: "bg-amber-500/10 text-amber-500",
    unknown: "bg-slate-500/10 text-slate-300",
  };

  return (
    <div className="size-full overflow-hidden p-4">
      <div className="mx-auto max-w-7xl">
        <div className="mb-4">
          <h1 className="text-2xl font-semibold text-foreground">
            {t("title", { ns: "views/organization" })}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("subtitle", { ns: "views/organization" })}
          </p>
        </div>

        <Tabs
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as "controllers" | "events")}
          className="space-y-4"
        >
          <TabsList>
            <TabsTrigger value="controllers">
              {t("tabs.controllers", { ns: "views/organization" })}
            </TabsTrigger>
            <TabsTrigger value="events">
              {t("tabs.events", { ns: "views/organization" })}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="controllers" className="space-y-4">
            <div className="flex justify-end">
              <Button
                onClick={() =>
                  setDeviceEditor({
                    mode: "create",
                    device: null,
                  })
                }
              >
                <LuPlus className="mr-2 size-4" />
                {t("button.addController", { ns: "views/organization" })}
              </Button>
            </div>

            <div className="rounded-lg border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("controllers.table.id", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("controllers.table.name", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("controllers.table.ipAddress", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("controllers.table.port", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("controllers.table.type", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("controllers.table.model", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("controllers.table.serial", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("controllers.table.status", { ns: "views/organization" })}</TableHead>
                    <TableHead className="text-right">
                      {t("controllers.table.actions", { ns: "views/organization" })}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {deviceList.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={9} className="py-8 text-center text-sm text-muted-foreground">
                        {t("controllers.empty", { ns: "views/organization" })}
                      </TableCell>
                    </TableRow>
                  ) : (
                    deviceList.map((device) => (
                      <TableRow key={device.id}>
                        <TableCell>{device.id}</TableCell>
                        <TableCell>{device.name || device.id}</TableCell>
                        <TableCell>{device.ip_address}</TableCell>
                        <TableCell>{device.port}</TableCell>
                        <TableCell>{device.type}</TableCell>
                        <TableCell>{device.model}</TableCell>
                        <TableCell>{device.serial_number || "-"}</TableCell>
                        <TableCell>
                          <span
                            className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${statusClasses[device.status?.toLowerCase()] ?? statusClasses.unknown}`}
                          >
                            {device.status || "offline"}
                          </span>
                        </TableCell>
                        <TableCell className="space-x-2 text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              setDeviceEditor({
                                mode: "edit",
                                device,
                              })
                            }
                          >
                            <LuPencil className="mr-1 size-4" />
                            {t("button.edit", { ns: "common" })}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleRetry(device.id)}
                          >
                            <LuRotateCcw className="mr-1 size-4" />
                            {t("button.retry", { ns: "common" })}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDeleteTarget({ id: device.id, name: device.name || device.id })}
                          >
                            <LuTrash2 className="mr-1 size-4" />
                            {t("button.delete", { ns: "common" })}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          <TabsContent value="events" className="space-y-4">
            <div className="flex items-center gap-3">
              <label className="text-sm font-medium text-foreground">
                {t("events.filter", { ns: "views/organization" })}
              </label>
              <Select value={selectedDeviceId} onValueChange={setSelectedDeviceId}>
                <SelectTrigger className="w-[220px]">
                  <SelectValue placeholder={t("events.all", { ns: "views/organization" })} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("events.all", { ns: "views/organization" })}</SelectItem>
                  {deviceList.map((device) => (
                    <SelectItem key={device.id} value={device.id}>
                      {device.name || device.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="rounded-lg border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("events.table.time", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("events.table.device", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("events.table.code", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("events.table.action", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("events.table.details", { ns: "views/organization" })}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {eventList.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="py-8 text-center text-sm text-muted-foreground">
                        {t("events.empty", { ns: "views/organization" })}
                      </TableCell>
                    </TableRow>
                  ) : (
                    eventList.map((event, index) => {
                      const details =
                        typeof event.data === "string"
                          ? event.data
                          : event.data && Object.keys(event.data).length > 0
                            ? JSON.stringify(event.data)
                            : JSON.stringify(event);

                      return (
                        <TableRow key={`${event.device_id ?? "device"}-${index}`}>
                          <TableCell>{event.time ?? event.Time ?? event.timestamp ?? "-"}</TableCell>
                          <TableCell>{event.device_name ?? event.device_id ?? "-"}</TableCell>
                          <TableCell>{String(event.code ?? event.Code ?? "-")}</TableCell>
                          <TableCell>{String(event.action ?? "-")}</TableCell>
                          <TableCell className="max-w-md truncate">{details}</TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            </div>
          </TabsContent>
        </Tabs>
      </div>

      {deviceEditor && (
        <DeviceEditorDialog
          mode={deviceEditor.mode}
          initialDevice={deviceEditor.device}
          onClose={() => setDeviceEditor(null)}
          onSave={handleSave}
        />
      )}

      {deleteTarget && (
        <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t("delete.title", { ns: "views/organization" })}</AlertDialogTitle>
              <AlertDialogDescription>
                {t("delete.description", { ns: "views/organization" ,  name: deleteTarget.name })}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t("button.cancel", { ns: "common" })}</AlertDialogCancel>
              <AlertDialogAction onClick={handleDelete}>
                {t("button.delete", { ns: "common" })}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  );
}

type DeviceEditorDialogProps = {
  mode: "create" | "edit";
  initialDevice: AccessControllerRecord | null;
  onClose: () => void;
  onSave: (values: DeviceFormValues, mode: "create" | "edit") => Promise<void>;
};

function DeviceEditorDialog({
  mode,
  initialDevice,
  onClose,
  onSave,
}: DeviceEditorDialogProps) {
  const { t } = useTranslation(["common", "views/organization"]);
  const [values, setValues] = useState<DeviceFormValues>({
    id: initialDevice?.id ?? "",
    name: initialDevice?.name ?? "",
    username: initialDevice?.username ?? "",
    password: initialDevice?.password ?? "",
    ipAddress: initialDevice?.ip_address ?? "",
    port: initialDevice?.port ?? 80,
  });

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    await onSave(values, mode);
    onClose();
  };

  return (
    <Dialog open={true} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "create"
              ? t("dialog.createTitle", { ns: "views/organization" })
              : t("dialog.editTitle", { ns: "views/organization" })}
          </DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("dialog.id", { ns: "views/organization" })}</label>
              <Input
                value={values.id}
                onChange={(event) => setValues({ ...values, id: event.target.value })}
                disabled={mode === "edit"}
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("dialog.name", { ns: "views/organization" })}</label>
              <Input
                value={values.name}
                onChange={(event) => setValues({ ...values, name: event.target.value })}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("dialog.username", { ns: "views/organization" })}</label>
              <Input
                value={values.username}
                onChange={(event) => setValues({ ...values, username: event.target.value })}
                placeholder="admin"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("dialog.password", { ns: "views/organization" })}</label>
              <Input
                type="password"
                value={values.password}
                onChange={(event) => setValues({ ...values, password: event.target.value })}
                placeholder="optional"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("dialog.ipAddress", { ns: "views/organization" })}</label>
              <Input
                value={values.ipAddress}
                onChange={(event) => setValues({ ...values, ipAddress: event.target.value })}
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("dialog.port", { ns: "views/organization" })}</label>
              <Input
                type="number"
                min={1}
                max={65535}
                value={values.port}
                onChange={(event) => setValues({ ...values, port: Number(event.target.value) || 80 })}
                required
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">{t("dialog.nonAuth", { ns: "views/organization" })}</p>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("button.cancel", { ns: "common" })}
            </Button>
            <Button type="submit">
              {mode === "create" ? t("button.add", { ns: "common" }) : t("button.save", { ns: "common" })}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
