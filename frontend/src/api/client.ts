export interface Member {
  id: number;
  name: string;
  role: "owner" | "family";
  avatar_color: string;
}

export interface RelativeItem {
  id: number;
  name: string;
  relation: string;
  side: string;
  phone?: string;
  city?: string;
  notes?: string;
  total_profiles?: number;
  active_profiles?: number;
  wa_link?: string | null;
}

export interface MeetingItem {
  id: number;
  profile_id: number;
  candidate_name?: string;
  disambiguation_tag?: string;
  stage: "proposing" | "scheduled" | "completed" | "cancelled";
  meeting_type: string;
  title: string;
  proposed_slots_text?: string;
  scheduled_at?: string | null;
  location_or_link?: string;
  participants?: string;
  pre_meeting_notes?: string;
  reminder_minutes: number;
  notify_phone_1: number;
  notify_phone_2: number;
  reminder_sent: number;
  post_meeting_notes?: string;
  call_recording_url?: string | null;
  call_transcript?: string;
  ai_call_summary?: string;
  whatsapp_slot_proposal_text?: string;
  google_calendar_url?: string | null;
  ics_download_url?: string;
  created_by_member: string;
  created_at: string;
}

export interface FamilyVote {
  id: number;
  profile_id: number;
  member_name: string;
  member_role: string;
  vote: "shortlist" | "discuss" | "pass";
  comment?: string;
  updated_at: string;
}

export interface FollowUpItem {
  id: number;
  profile_id: number;
  task: string;
  due_date?: string;
  assigned_to: string;
  ball_in_court: string;
  completed: number;
  created_by_member: string;
  full_name?: string;
  disambiguation_tag?: string;
}

export interface MediaAsset {
  id: number;
  profile_id?: number;
  import_job_id?: number;
  asset_type: string;
  file_name: string;
  url_path: string;
  mime_type?: string;
  transcript_or_ocr?: string;
  uploaded_by: string;
  created_at: string;
}

export interface InteractionItem {
  id: number;
  profile_id: number;
  interaction_type: string;
  title: string;
  summary?: string;
  raw_text?: string;
  transcript?: string;
  visibility: "shared" | "owner_only";
  created_by_member: string;
  occurred_at: string;
}

export interface Profile {
  id: number;
  full_name: string;
  gender?: string;
  dob?: string;
  age?: number;
  time_of_birth?: string;
  place_of_birth?: string;
  height?: string;
  marital_status?: string;
  diet?: string;
  smoking_drinking?: string;
  avatar_url?: string;
  disambiguation_tag?: string;

  education?: string;
  college?: string;
  occupation?: string;
  company?: string;
  annual_ctc?: string;
  work_mode?: string;
  current_city?: string;
  hometown?: string;
  relocation_openness?: string;

  father_details?: string;
  mother_details?: string;
  siblings_details?: string;
  family_type?: string;
  family_location?: string;
  caste_community?: string;
  sub_caste?: string;
  gotra?: string;
  manglik?: string;
  kundli_status?: string;
  kundli_gunas?: string;
  kundli_notes?: string;
  gotra_clash_alert?: string;

  source_channel?: string;
  source_name?: string;
  source_phone?: string;
  primary_contact_name?: string;
  primary_contact_relation?: string;
  primary_contact_phone?: string;
  candidate_phone?: string;
  linkedin_or_social?: string;

  status: string;
  ball_in_court: string;
  pass_reason?: string;
  snooze_until?: string;
  priority: string;

  our_biodata_sent: number;
  our_photos_sent: number;
  our_kundli_sent: number;
  numbers_exchanged: number;

  ai_fit_score?: number;
  fit_summary?: string;
  positives: string[];
  concerns: string[];
  missing_questions: string[];
  pre_call_brief?: string;
  shared_family_notes?: string;
  private_notes?: string | null;

  created_by_member: string;
  created_at: string;
  updated_at: string;

  family_votes?: FamilyVote[];
  open_follow_ups?: FollowUpItem[];
  media_assets?: MediaAsset[];
  interactions?: InteractionItem[];
  follow_ups?: FollowUpItem[];
  clean_whatsapp_summary?: string;
  wa_links?: {
    primary_contact?: string | null;
    candidate?: string | null;
    mediator?: string | null;
  };
}

const TOKEN_KEY = "rishta_auth_token";
const OUTBOX_DB_NAME = "rishta_offline_outbox";
const OUTBOX_STORE = "captures";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function apiFetch<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(options.headers || {});
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(path, {
    ...options,
    headers,
    credentials: "include",
  });

  if (!res.ok) {
    let errText = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      errText = data.detail || JSON.stringify(data);
    } catch {
      errText = await res.text();
    }
    throw new Error(errText);
  }
  return res.json();
}

// IndexedDB Offline Outbox Queue (for when Android is away from Mac Wi-Fi or Mac is asleep)
export interface OfflineCaptureItem {
  id?: number;
  raw_text: string;
  source_name: string;
  source_channel: string;
  created_at: string;
}

function openOutboxDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(OUTBOX_DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(OUTBOX_STORE)) {
        db.createObjectStore(OUTBOX_STORE, { keyPath: "id", autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function enqueueOfflineCapture(item: Omit<OfflineCaptureItem, "id">): Promise<void> {
  const db = await openOutboxDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OUTBOX_STORE, "readwrite");
    tx.objectStore(OUTBOX_STORE).add(item);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function listOfflineCaptures(): Promise<OfflineCaptureItem[]> {
  try {
    const db = await openOutboxDB();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(OUTBOX_STORE, "readonly");
      const req = tx.objectStore(OUTBOX_STORE).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  } catch {
    return [];
  }
}

export async function removeOfflineCapture(id: number): Promise<void> {
  const db = await openOutboxDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OUTBOX_STORE, "readwrite");
    tx.objectStore(OUTBOX_STORE).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}
