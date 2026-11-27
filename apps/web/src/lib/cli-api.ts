/**
 * CLI API client — wrappers for the simulation CLI endpoint.
 */

import { apiFetch } from "./api";

export interface CLIResponse {
  output: string;
  prompt: string;
  mode: string;
  /** Device is reading the next line itself (Password:, Press RETURN, ...). */
  awaiting_input?: boolean;
  /** Do not echo the next line (password prompts). */
  input_hidden?: boolean;
  /** Syslog messages the console prints after this command. */
  console?: string[];
}

export interface CompleteResponse {
  completed: string;
  prompt: string;
}

export interface HelpResponse {
  help: string;
  prompt: string;
}

export async function sendCLICommand(
  sessionId: string,
  deviceId: string,
  command: string,
): Promise<CLIResponse> {
  return apiFetch<CLIResponse>(`/labs/simulations/${sessionId}/cli/`, {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, command, action: "execute" }),
  });
}

export async function completeCLICommand(
  sessionId: string,
  deviceId: string,
  partial: string,
): Promise<CompleteResponse> {
  return apiFetch<CompleteResponse>(`/labs/simulations/${sessionId}/cli/`, {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, command: partial, action: "complete" }),
  });
}

export async function getCLIHelp(
  sessionId: string,
  deviceId: string,
  partial: string,
): Promise<HelpResponse> {
  return apiFetch<HelpResponse>(`/labs/simulations/${sessionId}/cli/`, {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, command: partial, action: "help" }),
  });
}
