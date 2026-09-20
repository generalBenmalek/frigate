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
import ActivityIndicator from "@/components/indicators/activity-indicator";
import { LuPencil, LuPlus, LuTrash2 } from "react-icons/lu";
import { IoMdPeople } from "react-icons/io";

type GroupRecord = {
  id: string;
  group_name: string;
};

type EmployeeRecord = {
  id: string;
  first_name: string;
  last_name: string;
  group_id: string;
  group_name: string;
};

type GroupFormValues = {
  id: string;
  groupName: string;
};

type EmployeeFormValues = {
  id: string;
  firstName: string;
  lastName: string;
  groupId: string;
};

type GroupEditorState = {
  mode: "create" | "edit";
  group: GroupRecord | null;
};

type EmployeeEditorState = {
  mode: "create" | "edit";
  employee: EmployeeRecord | null;
};

type DeleteTarget =
  | { type: "group"; id: string; label: string }
  | { type: "employee"; id: string; label: string };

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

export default function OrganizationPage() {
  const { t } = useTranslation(["common", "views/organization"]);
  const [activeTab, setActiveTab] = useState<"employees" | "groups">(
    "employees",
  );
  const [groupEditor, setGroupEditor] = useState<GroupEditorState | null>(null);
  const [employeeEditor, setEmployeeEditor] =
    useState<EmployeeEditorState | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);

  useEffect(() => {
    document.title = t("documentTitle", { ns: "views/organization" });
  }, [t]);

  const {
    data: groups,
    mutate: refreshGroups,
    error: groupsError,
  } = useSWR<GroupRecord[]>("organization/groups", {
    revalidateOnFocus: false,
  });
  const {
    data: employees,
    mutate: refreshEmployees,
    error: employeesError,
  } = useSWR<EmployeeRecord[]>("organization/employees", {
    revalidateOnFocus: false,
  });

  useEffect(() => {
    if (groupsError) {
      toast.error(
        getErrorMessage(
          groupsError,
          t("toast.error.loadGroupsFailed", { ns: "views/organization" }),
        ),
        { position: "top-center" },
      );
    }
  }, [groupsError, t]);

  useEffect(() => {
    if (employeesError) {
      toast.error(
        getErrorMessage(
          employeesError,
          t("toast.error.loadEmployeesFailed", { ns: "views/organization" }),
        ),
        { position: "top-center" },
      );
    }
  }, [employeesError, t]);

  const groupList = groups ?? [];
  const employeeList = employees ?? [];

  const groupSelectOptions = useMemo(
    () => groupList.map((group) => ({ value: group.id, label: group.group_name })),
    [groupList],
  );

  const reloadAll = async () => {
    await Promise.all([refreshGroups(), refreshEmployees()]);
  };

  const handleSaveGroup = async (values: GroupFormValues, mode: "create" | "edit") => {
    try {
      if (mode === "create") {
        await axios.post("groups", {
          id: values.id,
          group_name: values.groupName,
        });
        toast.success(
          t("toast.success.createdGroup", { ns: "views/organization" }),
          {
            position: "top-center",
          },
        );
      } else {
        await axios.put(`groups/${values.id}`, {
          group_name: values.groupName,
        });
        toast.success(
          t("toast.success.updatedGroup", { ns: "views/organization" }),
          {
            position: "top-center",
          },
        );
      }

      await reloadAll();
    } catch (error) {
      toast.error(
        getErrorMessage(error, t("toast.error.saveGroupFailed", { ns: "views/organization" })),
        { position: "top-center" },
      );
      throw error;
    }
  };

  const handleSaveEmployee = async (
    values: EmployeeFormValues,
    mode: "create" | "edit",
  ) => {
    try {
      if (mode === "create") {
        await axios.post("employees", {
          id: values.id,
          first_name: values.firstName,
          last_name: values.lastName,
          group_id: values.groupId,
        });
        toast.success(
          t("toast.success.createdEmployee", { ns: "views/organization" }),
          {
            position: "top-center",
          },
        );
      } else {
        await axios.put(`employees/${values.id}`, {
          first_name: values.firstName,
          last_name: values.lastName,
          group_id: values.groupId,
        });
        toast.success(
          t("toast.success.updatedEmployee", { ns: "views/organization" }),
          {
            position: "top-center",
          },
        );
      }

      await refreshEmployees();
    } catch (error) {
      toast.error(
        getErrorMessage(
          error,
          t("toast.error.saveEmployeeFailed", { ns: "views/organization" }),
        ),
        { position: "top-center" },
      );
      throw error;
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) {
      return;
    }

    try {
      if (deleteTarget.type === "group") {
        await axios.delete(`groups/${deleteTarget.id}`);
        toast.success(
          t("toast.success.deletedGroup", { ns: "views/organization" }),
          {
            position: "top-center",
          },
        );
      } else {
        await axios.delete(`employees/${deleteTarget.id}`);
        toast.success(
          t("toast.success.deletedEmployee", { ns: "views/organization" }),
          {
            position: "top-center",
          },
        );
      }

      await reloadAll();
      setDeleteTarget(null);
    } catch (error) {
      toast.error(
        getErrorMessage(
          error,
          t("toast.error.deleteFailed", { ns: "views/organization" }),
        ),
        { position: "top-center" },
      );
    }
  };

  if (!groups || !employees) {
    return (
      <div className="size-full">
        <ActivityIndicator className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2" />
      </div>
    );
  }

  return (
    <div className="size-full overflow-y-auto p-4 md:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-4">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
            <IoMdPeople className="size-5" />
          </div>
          <div>
            <h1 className="text-xl font-semibold">
              {t("title", { ns: "views/organization" })}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t("subtitle", { ns: "views/organization" })}
            </p>
          </div>
        </div>

        <Tabs
          value={activeTab}
          onValueChange={(value) => setActiveTab(value as "employees" | "groups")}
          className="w-full"
        >
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="employees">
              {t("tabs.employees", { ns: "views/organization" })}
            </TabsTrigger>
            <TabsTrigger value="groups">
              {t("tabs.groups", { ns: "views/organization" })}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="employees" className="mt-4">
            <div className="rounded-xl border bg-card p-4 shadow-sm">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-medium">
                    {t("employees.title", { ns: "views/organization" })}
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    {t("employees.subtitle", { ns: "views/organization" })}
                  </p>
                </div>
                <Button
                  onClick={() =>
                    setEmployeeEditor({
                      mode: "create",
                      employee: null,
                    })
                  }
                >
                  <LuPlus className="mr-2 size-4" />
                  {t("button.addEmployee", { ns: "views/organization" })}
                </Button>
              </div>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("employees.table.id", { ns: "views/organization" })}</TableHead>
                    <TableHead>
                      {t("employees.table.firstName", { ns: "views/organization" })}
                    </TableHead>
                    <TableHead>
                      {t("employees.table.lastName", { ns: "views/organization" })}
                    </TableHead>
                    <TableHead>
                      {t("employees.table.group", { ns: "views/organization" })}
                    </TableHead>
                    <TableHead className="text-right">
                      {t("employees.table.actions", { ns: "views/organization" })}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {employeeList.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                        {t("employees.empty", { ns: "views/organization" })}
                      </TableCell>
                    </TableRow>
                  ) : (
                    employeeList.map((employee) => (
                      <TableRow key={employee.id}>
                        <TableCell className="font-medium">{employee.id}</TableCell>
                        <TableCell>{employee.first_name}</TableCell>
                        <TableCell>{employee.last_name}</TableCell>
                        <TableCell>{employee.group_name}</TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() =>
                                setEmployeeEditor({
                                  mode: "edit",
                                  employee,
                                })
                              }
                            >
                              <LuPencil className="mr-2 size-4" />
                              {t("button.edit", { ns: "common" })}
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() =>
                                setDeleteTarget({
                                  type: "employee",
                                  id: employee.id,
                                  label: `${employee.first_name} ${employee.last_name}`,
                                })
                              }
                            >
                              <LuTrash2 className="mr-2 size-4" />
                              {t("button.delete", { ns: "common" })}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          <TabsContent value="groups" className="mt-4">
            <div className="rounded-xl border bg-card p-4 shadow-sm">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-medium">
                    {t("groups.title", { ns: "views/organization" })}
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    {t("groups.subtitle", { ns: "views/organization" })}
                  </p>
                </div>
                <Button
                  onClick={() =>
                    setGroupEditor({
                      mode: "create",
                      group: null,
                    })
                  }
                >
                  <LuPlus className="mr-2 size-4" />
                  {t("button.addGroup", { ns: "views/organization" })}
                </Button>
              </div>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("groups.table.id", { ns: "views/organization" })}</TableHead>
                    <TableHead>{t("groups.table.name", { ns: "views/organization" })}</TableHead>
                    <TableHead className="text-right">
                      {t("groups.table.actions", { ns: "views/organization" })}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {groupList.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={3} className="py-8 text-center text-muted-foreground">
                        {t("groups.empty", { ns: "views/organization" })}
                      </TableCell>
                    </TableRow>
                  ) : (
                    groupList.map((group) => (
                      <TableRow key={group.id}>
                        <TableCell className="font-medium">{group.id}</TableCell>
                        <TableCell>{group.group_name}</TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() =>
                                setGroupEditor({
                                  mode: "edit",
                                  group,
                                })
                              }
                            >
                              <LuPencil className="mr-2 size-4" />
                              {t("button.edit", { ns: "common" })}
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() =>
                                setDeleteTarget({
                                  type: "group",
                                  id: group.id,
                                  label: group.group_name,
                                })
                              }
                            >
                              <LuTrash2 className="mr-2 size-4" />
                              {t("button.delete", { ns: "common" })}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </TabsContent>
        </Tabs>
      </div>

      {groupEditor && (
        <GroupEditorDialog
          state={groupEditor}
          onClose={() => setGroupEditor(null)}
          onSave={handleSaveGroup}
        />
      )}

      {employeeEditor && (
        <EmployeeEditorDialog
          state={employeeEditor}
          groups={groupSelectOptions}
          onClose={() => setEmployeeEditor(null)}
          onSave={handleSaveEmployee}
        />
      )}

      <AlertDialog open={deleteTarget !== null} onOpenChange={() => setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {deleteTarget?.type === "group"
                ? t("delete.group.title", { ns: "views/organization" })
                : t("delete.employee.title", { ns: "views/organization" })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {deleteTarget?.type === "group"
                ? t("delete.group.description", {
                    ns: "views/organization",
                    name: deleteTarget.label,
                  })
                : t("delete.employee.description", {
                    ns: "views/organization",
                    name: deleteTarget?.label,
                  })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteTarget(null)}>
              {t("button.cancel", { ns: "common" })}
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete}>
              {t("button.delete", { ns: "common" })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function GroupEditorDialog({
  state,
  onClose,
  onSave,
}: {
  state: GroupEditorState;
  onClose: () => void;
  onSave: (values: GroupFormValues, mode: "create" | "edit") => Promise<void>;
}) {
  const { t } = useTranslation(["common", "views/organization"]);
  const [values, setValues] = useState<GroupFormValues>({
    id: state.group?.id ?? "",
    groupName: state.group?.group_name ?? "",
  });
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (state.mode === "create") {
      setValues({ id: "", groupName: "" });
    } else {
      setValues({
        id: state.group?.id ?? "",
        groupName: state.group?.group_name ?? "",
      });
    }
  }, [state]);

  const title =
    state.mode === "create"
      ? t("groupDialog.createTitle", { ns: "views/organization" })
      : t("groupDialog.editTitle", { ns: "views/organization" });

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSaving(true);
    try {
      await onSave(values, state.mode);
      onClose();
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <label className="text-sm font-medium">
              {t("groupDialog.id", { ns: "views/organization" })}
            </label>
            <Input
              value={values.id}
              disabled={state.mode === "edit"}
              onChange={(event) =>
                setValues((current) => ({ ...current, id: event.target.value }))
              }
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">
              {t("groupDialog.name", { ns: "views/organization" })}
            </label>
            <Input
              value={values.groupName}
              onChange={(event) =>
                setValues((current) => ({
                  ...current,
                  groupName: event.target.value,
                }))
              }
              required
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("button.cancel", { ns: "common" })}
            </Button>
            <Button type="submit" disabled={isSaving}>
              {t("button.save", { ns: "common" })}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EmployeeEditorDialog({
  state,
  groups,
  onClose,
  onSave,
}: {
  state: EmployeeEditorState;
  groups: { value: string; label: string }[];
  onClose: () => void;
  onSave: (values: EmployeeFormValues, mode: "create" | "edit") => Promise<void>;
}) {
  const { t } = useTranslation(["common", "views/organization"]);
  const [values, setValues] = useState<EmployeeFormValues>({
    id: state.employee?.id ?? "",
    firstName: state.employee?.first_name ?? "",
    lastName: state.employee?.last_name ?? "",
    groupId: state.employee?.group_id ?? groups[0]?.value ?? "",
  });
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setValues({
      id: state.employee?.id ?? "",
      firstName: state.employee?.first_name ?? "",
      lastName: state.employee?.last_name ?? "",
      groupId: state.employee?.group_id ?? groups[0]?.value ?? "",
    });
  }, [groups, state]);

  const title =
    state.mode === "create"
      ? t("employeeDialog.createTitle", { ns: "views/organization" })
      : t("employeeDialog.editTitle", { ns: "views/organization" });

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSaving(true);
    try {
      await onSave(values, state.mode);
      onClose();
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <label className="text-sm font-medium">
              {t("employeeDialog.id", { ns: "views/organization" })}
            </label>
            <Input
              value={values.id}
              disabled={state.mode === "edit"}
              onChange={(event) =>
                setValues((current) => ({ ...current, id: event.target.value }))
              }
              required
            />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">
                {t("employeeDialog.firstName", { ns: "views/organization" })}
              </label>
              <Input
                value={values.firstName}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    firstName: event.target.value,
                  }))
                }
                required
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">
                {t("employeeDialog.lastName", { ns: "views/organization" })}
              </label>
              <Input
                value={values.lastName}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    lastName: event.target.value,
                  }))
                }
                required
              />
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">
              {t("employeeDialog.group", { ns: "views/organization" })}
            </label>
            <Select
              value={values.groupId}
              onValueChange={(value) =>
                setValues((current) => ({ ...current, groupId: value }))
              }
              disabled={groups.length === 0}
            >
              <SelectTrigger>
                <SelectValue
                  placeholder={t("employeeDialog.groupPlaceholder", {
                    ns: "views/organization",
                  })}
                />
              </SelectTrigger>
              <SelectContent>
                {groups.map((group) => (
                  <SelectItem key={group.value} value={group.value}>
                    {group.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {groups.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {t("employeeDialog.noGroups", { ns: "views/organization" })}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("button.cancel", { ns: "common" })}
            </Button>
            <Button type="submit" disabled={isSaving || groups.length === 0}>
              {t("button.save", { ns: "common" })}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
