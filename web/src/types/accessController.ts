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
  verification_status?: "pending" | "unverified" | "valid" | "warning" | "unknown";
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
  start: "", end: "", name: "", userId: "", cardNo: "", status: "",
};
