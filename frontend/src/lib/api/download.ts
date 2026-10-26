/**
 * Binary responses (file downloads) from the API.
 *
 * `request()` in client.ts is JSON-only by contract, which is right for every screen but wrong for a
 * workbook: parsing it as JSON would corrupt it. This keeps the same credentials, the same access token
 * and the same `{code,message,details}` error envelope, and adds the plumbing a browser download needs
 * (filename from `Content-Disposition`, then a revoke-able object URL).
 */
import { ApiError_, type ApiError, getAccessToken } from "./client";

const BASE = "/api/v1";

export type DownloadedFile = {
  filename: string;
  blob: Blob;
  rows: number | null;
  truncated: boolean;
};

export async function downloadFile(path: string, body?: unknown): Promise<DownloadedFile> {
  const response = await fetch(`${BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: {
      "content-type": "application/json",
      ...(getAccessToken() ? { authorization: `Bearer ${getAccessToken()}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null; // a non-JSON failure body still becomes the uniform error below
    }
    throw errorFrom(response.status, payload);
  }

  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? "export.xlsx";
  const rows = Number.parseInt(response.headers.get("x-export-rows") ?? "", 10);
  return {
    filename,
    blob: await response.blob(),
    rows: Number.isNaN(rows) ? null : rows,
    truncated: response.headers.get("x-export-truncated") === "1",
  };
}

function errorFrom(status: number, payload: unknown): ApiError_ {
  return new ApiError_(status, (payload ?? null) as Partial<ApiError> | null, `Request failed (${status})`);
}

/** Trigger the browser save, then release the object URL so the blob does not linger in memory. */
export function saveFile(file: DownloadedFile): void {
  const url = URL.createObjectURL(file.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = file.filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
