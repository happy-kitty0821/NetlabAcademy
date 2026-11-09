/**
 * CLI API client — wrappers for the simulation CLI endpoint.
 */

import { apiFetch } from "./api";

export interface CLIResponse {
  output: string;
  prompt: string;
  mode: string;
}

export async function sendCLICommand(
  sessionId: string,
  deviceId: string,
  command: string,
): Promise<CLIResponse> {
  return apiFetch<CLIResponse>(`/labs/simulations/${sessionId}/cli/`, {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, command }),
  });
}
