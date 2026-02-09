export interface FileArtifact {
  name: string;
  content: string;
  size: number;
}

export interface IncidentReport {
  summary: string;
  timeline: string[];
  root_causes: string[];
  evidence: string[];
  mitigations: string[];
  follow_ups: string[];
  confidence: number;
}

export interface AnalysisState {
  status: 'idle' | 'loading' | 'success' | 'error';
  rawResponse: string | null;
  parsedReport: IncidentReport | null;
  error: string | null;
}
