"use client"

import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"

import { api } from "./client"
import type { JsonValue, ReviewStatus, RunStatus } from "./schemas"

const ACTIVE_RUN_STATUSES: ReadonlySet<RunStatus> = new Set(["queued", "scanning", "running", "finalizing"])
const ACTIVE_POLL_MS = 2500

export const DOCUMENTS_PAGE_SIZE = 50
export const REVIEWS_PAGE_SIZE = 50
export const TIMELINE_PAGE_SIZE = 50

export const isActiveRun = (status: RunStatus) => ACTIVE_RUN_STATUSES.has(status)

export const keys = {
  overview: ["overview"] as const,
  health: ["health"] as const,
  runs: (offset: number) => ["runs", offset] as const,
  run: (id: string) => ["run", id] as const,
  timeline: (id: string, offset: number) => ["timeline", id, offset] as const,
  documents: (filters: object) => ["documents", filters] as const,
  document: (id: string) => ["document", id] as const,
  extraction: (id: string, versionId?: string) => ["extraction", id, versionId ?? "current"] as const,
  blocks: (id: string, versionId?: string) => ["blocks", id, versionId ?? "current"] as const,
  chunks: (id: string, versionId?: string) => ["chunks", id, versionId ?? "current"] as const,
  reviews: (status: ReviewStatus) => ["reviews", status] as const,
  search: (q: string, kind?: string) => ["search", q, kind ?? "all"] as const,
}

export function useOverview() {
  return useQuery({
    queryKey: keys.overview,
    queryFn: api.overview,
    refetchInterval: (query) =>
      query.state.data?.recent_runs.some((run) => isActiveRun(run.status)) ? ACTIVE_POLL_MS : 15000,
  })
}

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: api.health, refetchInterval: 30000 })
}

export function useRuns(offset: number) {
  return useQuery({
    queryKey: keys.runs(offset),
    queryFn: () => api.runs({ limit: 25, offset }),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => isActiveRun(run.status)) ? ACTIVE_POLL_MS : 15000,
  })
}

export function useRun(id: string) {
  return useQuery({
    queryKey: keys.run(id),
    queryFn: () => api.run(id),
    refetchInterval: (query) =>
      query.state.data && isActiveRun(query.state.data.run.status) ? ACTIVE_POLL_MS : false,
  })
}

export function useTimeline(id: string, offset: number, active: boolean) {
  return useQuery({
    queryKey: keys.timeline(id, offset),
    queryFn: () => api.timeline(id, { limit: TIMELINE_PAGE_SIZE, offset }),
    placeholderData: keepPreviousData,
    refetchInterval: active ? ACTIVE_POLL_MS : false,
  })
}

export function useStartRun() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.startRun,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["runs"] })
      void client.invalidateQueries({ queryKey: keys.overview })
    },
  })
}

export function useDocuments(filters: { kind?: string; q?: string; offset: number }) {
  return useQuery({
    queryKey: keys.documents(filters),
    queryFn: () =>
      api.documents({
        limit: DOCUMENTS_PAGE_SIZE,
        offset: filters.offset,
        ...(filters.kind ? { kind: filters.kind } : {}),
        ...(filters.q ? { q: filters.q } : {}),
      }),
    placeholderData: keepPreviousData,
  })
}

export function useDocument(id: string) {
  return useQuery({ queryKey: keys.document(id), queryFn: () => api.document(id) })
}

export function useExtraction(id: string, versionId?: string) {
  return useQuery({ queryKey: keys.extraction(id, versionId), queryFn: () => api.extraction(id, versionId) })
}

export function useBlocks(id: string, versionId?: string, enabled = true) {
  return useQuery({ queryKey: keys.blocks(id, versionId), queryFn: () => api.blocks(id, versionId), enabled })
}

export function useChunks(id: string, versionId?: string) {
  return useQuery({ queryKey: keys.chunks(id, versionId), queryFn: () => api.chunks(id, versionId) })
}

export function useReviews(status: ReviewStatus) {
  return useInfiniteQuery({
    queryKey: keys.reviews(status),
    queryFn: ({ pageParam }) => api.reviews({ status, limit: REVIEWS_PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined),
  })
}

export function useResolveReview() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { id: string; action: "approve" } | { id: string; action: "edit"; value: JsonValue }) =>
      input.action === "approve"
        ? api.approveReview(input.id, {})
        : api.editReview(input.id, { value: input.value }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["reviews"] })
      void client.invalidateQueries({ queryKey: ["extraction"] })
      void client.invalidateQueries({ queryKey: ["documents"] })
      void client.invalidateQueries({ queryKey: keys.overview })
    },
  })
}

export function useSearch(q: string, kind?: string) {
  return useQuery({
    queryKey: keys.search(q, kind),
    queryFn: () => api.search({ q, limit: 10, ...(kind ? { kind } : {}) }),
    enabled: q.trim().length >= 2,
    placeholderData: keepPreviousData,
  })
}

export function useOpenDeadLetters() {
  return useQuery({ queryKey: ["dead-letters", "open"], queryFn: () => api.deadLetters({ status: "open", limit: 1 }) })
}

export function useReplayDeadLetter() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.replayDeadLetter,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["run"] })
      void client.invalidateQueries({ queryKey: ["runs"] })
      void client.invalidateQueries({ queryKey: keys.overview })
    },
  })
}
