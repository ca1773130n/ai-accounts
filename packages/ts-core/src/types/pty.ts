export interface PtySessionDTO {
  session_id: string;
}

export interface PtySpawnRequest {
  backend_id: string;
  command: string[];
  cols?: number;
  rows?: number;
}
