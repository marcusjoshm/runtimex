import axios from 'axios';
import { API_BASE } from './config';

// Define interfaces to match backend models. All field names are snake_case
// to match the wire format normalized in U8.
export interface Step {
  id: string;
  name: string;
  // Renamed from `type` -> `step_type` so the discriminator field doesn't
  // clash with TypeScript's reserved-ish `type` keyword in JSX contexts and
  // matches the backend's `Step.step_type` ORM column.
  step_type: string;
  // Duration in SECONDS (float). The pre-U8 wire format used integer minutes
  // and floor-divided on the server, which truncated sub-minute steps to 0.
  // Frontend formatters convert seconds -> minutes (or "<1 min") for display.
  duration_seconds: number;
  status: string;
  dependencies: string[];
  notes?: string;
  resource_required?: string;
  scheduled_start_time?: string;
  scheduled_end_time?: string;
  actual_start_time?: string;
  first_start_time?: string;
  actual_end_time?: string;
  // Server-snapshot of accumulated runtime. The Runner derives a per-tick
  // elapsed value from `actual_start_time` for sub-second responsiveness;
  // this field is the cross-pause source of truth and is used for display
  // when a step is PAUSED.
  elapsed_seconds?: number;
  // Condition this step belongs to. Always present for persisted steps once
  // U1 is shipped; legacy data is auto-backfilled to a "Main" Condition.
  condition_id?: string;
  // U3 cascading time: opt-in directive copied verbatim from the wire. Either
  // the literal string "previous" (server resolves to the immediately
  // preceding sibling in the same Condition) or a sibling Step's id. Absent /
  // undefined means "no inherit". The Designer's per-step toggle writes
  // "previous"; the Runner does NOT re-derive countdown from this field --
  // the server pre-seeds elapsed_seconds on START so the existing
  // ``duration_seconds - elapsed_seconds`` math just works.
  inherits_elapsed_from?: string;
}

// Condition: a named grouping of steps within an Experiment. Multiple
// conditions run in parallel (e.g. "Dish 1 / Dish 2 / Dish 3"), can share
// resources, and can drift in shape from each other. The `color` is one of
// the 10 predefined palette keys (slate, coral, forest, lavender, amber,
// teal, magenta, mint, navy, gold) -- see ConditionPaletteSwatch.tsx for the
// canonical list and the MUI mapping.
export interface Condition {
  id: string;
  experiment_id: string;
  name: string;
  color: string;
  order_index: number;
  description?: string;
}

export interface Experiment {
  id: string;
  name: string;
  description: string;
  steps: Step[];
  // U1 ships this as a sibling array on the wire. Optional in the type so
  // legacy mock data and partial-update payloads still type-check.
  conditions?: Condition[];
  owner?: string;
  shared_with?: Record<string, string>; // username -> permission
}

// Resource-conflict descriptor. Returned by GET /api/experiments/<id>/conflicts
// and surfaced inline in the PUT response (`{ ...experiment, conflicts: [...] }`)
// so the Designer can warn on save without an extra round-trip. Snake_case
// since pre-U6.
export interface Conflict {
  step_a: string;
  step_b: string;
  resource: string;
  overlap_seconds: number;
  step_a_name: string;
  step_b_name: string;
  // Condition labels (U2). Always populated server-side; the name falls back
  // to "Unknown" when the step's condition_id can't be resolved against the
  // experiment's Condition cache (defensive against mid-edit race / legacy
  // data). condition_*_id may be null for pre-U1 steps that escaped backfill.
  condition_a_id?: string | null;
  condition_a_name: string;
  condition_b_id?: string | null;
  condition_b_name: string;
}

// Response shape for createExperiment / updateExperiment. The PUT path
// includes `conflicts`; the POST path doesn't (yet) but typing it as
// optional means the Designer can read it uniformly.
export type ExperimentSaveResponse = Experiment & { conflicts?: Conflict[] };

// Create API client
const apiClient = {
  // Experiment API methods
  getExperiments: async (): Promise<Experiment[]> => {
    const response = await axios.get(`${API_BASE}/experiments`);
    return response.data;
  },

  getExperiment: async (id: string): Promise<Experiment> => {
    const response = await axios.get(`${API_BASE}/experiments/${id}`);
    return response.data;
  },

  createExperiment: async (experiment: Omit<Experiment, 'id'>): Promise<Experiment> => {
    const response = await axios.post(`${API_BASE}/experiments`, experiment);
    return response.data;
  },

  updateExperiment: async (
    id: string,
    experiment: Partial<Experiment>
  ): Promise<ExperimentSaveResponse> => {
    // Backend returns the full experiment payload + a `conflicts: Conflict[]`
    // field (U6). Callers that don't care about conflicts can ignore it; the
    // Designer reads it on save to surface a warning Alert.
    const response = await axios.put(`${API_BASE}/experiments/${id}`, experiment);
    return response.data;
  },

  // Fetch the current conflict list for an experiment. Mirrors the server's
  // pure `Scheduler.check_for_conflicts` -- so the Runner can re-fetch on
  // every `experiment_update` socket push without worrying about staleness.
  getConflicts: async (experimentId: string): Promise<Conflict[]> => {
    const response = await axios.get(
      `${API_BASE}/experiments/${experimentId}/conflicts`
    );
    return response.data;
  },

  // Step API methods
  startStep: async (stepId: string): Promise<Experiment> => {
    const response = await axios.post(`${API_BASE}/steps/${stepId}/start`);
    return response.data;
  },

  pauseStep: async (stepId: string): Promise<Experiment> => {
    const response = await axios.post(`${API_BASE}/steps/${stepId}/pause`);
    return response.data;
  },

  completeStep: async (stepId: string): Promise<Experiment> => {
    const response = await axios.post(`${API_BASE}/steps/${stepId}/complete`);
    return response.data;
  },

  skipStep: async (stepId: string): Promise<Experiment> => {
    const response = await axios.post(`${API_BASE}/steps/${stepId}/skip`);
    return response.data;
  },

  getUserExperiments: async (): Promise<Experiment[]> => {
    const response = await axios.get(`${API_BASE}/user/experiments`);
    return response.data;
  },

  // Export experiment
  exportExperiment: async (experimentId: string): Promise<void> => {
    // The backend's export route is now @jwt_required (U3), so we must send
    // the Authorization header — `window.location.href` won't. Pull the
    // payload as a Blob via axios (which carries the default Authorization
    // header set by bootstrapAuth/login) and trigger the download from a
    // temporary anchor element.
    const response = await axios.get(
      `${API_BASE}/experiments/${experimentId}/export`,
      { responseType: 'blob' }
    );

    const blob = new Blob([response.data], {
      type: response.headers['content-type'] || 'application/json',
    });
    const objectUrl = URL.createObjectURL(blob);

    // Try to honor Content-Disposition's filename, fall back to a sensible default.
    let filename = `experiment-${experimentId}.json`;
    const disposition = response.headers['content-disposition'];
    if (typeof disposition === 'string') {
      const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
      if (match && match[1]) {
        filename = decodeURIComponent(match[1]);
      }
    }

    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(objectUrl);
  },

  // Import experiment
  importExperiment: async (file: File): Promise<Experiment> => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await axios.post(`${API_BASE}/experiments/import`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
    return response.data;
  },

  // Template management
  getTemplates: async (): Promise<any[]> => {
    const response = await axios.get(`${API_BASE}/templates`);
    return response.data;
  },

  createTemplate: async (experimentId: string, name: string): Promise<any> => {
    // Wire field is `experiment_id` (U8 snake_case). The TS function signature
    // keeps camelCase parameters because they're just locals -- the wire
    // shape is what U8 normalizes.
    const response = await axios.post(`${API_BASE}/templates`, {
      experiment_id: experimentId,
      name
    });
    return response.data;
  },

  deleteTemplate: async (templateId: string): Promise<void> => {
    await axios.delete(`${API_BASE}/templates/${templateId}`);
  },

  createFromTemplate: async (templateId: string, name?: string): Promise<Experiment> => {
    const response = await axios.post(`${API_BASE}/experiments/create-from-template/${templateId}`, {
      name
    });
    return response.data;
  },

  // Share experiment
  shareExperiment: async (experimentId: string, username: string, permission: 'view' | 'edit'): Promise<void> => {
    await axios.post(`${API_BASE}/experiments/${experimentId}/share`, {
      username,
      permission
    });
  }
};

export default apiClient;
