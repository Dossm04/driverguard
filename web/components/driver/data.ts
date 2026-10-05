"use client";

import { useQuery } from "@tanstack/react-query";

import { api, ApiError, type DriverMe } from "@/lib/api";

/** Профиль текущего водителя (GET /drivers/me) — общий источник для всех экранов PWA. */
export function useDriverMe() {
  return useQuery({
    queryKey: ["driver-me"],
    queryFn: () => api<DriverMe>("/drivers/me"),
    refetchInterval: 30_000,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 1,
  });
}
