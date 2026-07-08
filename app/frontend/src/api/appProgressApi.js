import { request } from "./projectApi.js";

export function getAppProgress() {
  return request("/api/app/progress");
}
