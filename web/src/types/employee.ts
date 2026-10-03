export type EmployeeSource = {
  id: string;
  controller_id: string;
  user_id: string;
  name: string;
  active: boolean;
};

export type EmployeeRecord = {
  id: string;
  name: string | null;
  display_name: string;
  username: string | null;
  enabled: boolean;
  super_employee: boolean;
  pending: boolean;
  has_face: boolean;
  face_name: string | null;
  sources: EmployeeSource[];
  permissions: {
    controller_id: string;
    doors: string[];
    overridden: boolean;
  }[];
};

export type EmployeeSettings = {
  enabled: boolean;
  port: number;
  sync: {
    controller_id: string;
    status: "ok" | "limited" | "unsupported" | "failed";
    checked_at: number;
    last_success: number | null;
  }[];
};

export type EmployeeSession = {
  authenticated: boolean;
  csrf_token: string;
  name?: string;
  has_face?: boolean;
  enabled?: boolean;
};

export type EmployeeAccessOption = {
  camera: string;
  controller_id: string;
  controller_name: string;
  doors: { id: string; name: string }[];
};

export type EmployeeAccessResult = {
  success: boolean;
  reason: string;
  identity_verified?: boolean;
  request_id?: string;
  door_command?: "not_sent" | "accepted" | "unknown";
};

export type EmployeeAuditRecord = {
  id: string;
  employee_id: string;
  created_at: number;
  camera: string;
  controller_id: string;
  door_id: string;
  status: string;
  score: number | null;
  result: EmployeeAccessResult | Record<string, never>;
};
