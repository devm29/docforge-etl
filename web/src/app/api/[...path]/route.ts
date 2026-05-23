import type { NextRequest } from "next/server"

export const dynamic = "force-dynamic"

const ORIGIN = process.env.DOCFORGE_API_ORIGIN ?? "http://localhost:8103"
const REQUEST_HEADERS = ["accept", "content-type"] as const
const RESPONSE_HEADERS = ["content-type", "content-disposition", "cache-control", "x-content-type-options"] as const

/**
 * Forwards /api/* to the FastAPI service. The bearer token stays on the server: browsers never see
 * it, and the API attributes review decisions to the principal the token belongs to.
 */
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await context.params
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`, ORIGIN)

  const headers = new Headers()
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name)
    if (value) headers.set(name, value)
  }
  const token = process.env.DOCFORGE_API_TOKEN
  if (token) headers.set("authorization", `Bearer ${token}`)

  let upstream: Response
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      cache: "no-store",
      redirect: "manual",
      ...(request.method === "GET" ? {} : { body: await request.arrayBuffer() }),
    })
  } catch {
    return Response.json(
      { error: { code: "api_unreachable", message: `The DocForge API at ${ORIGIN} is not reachable.` } },
      { status: 502 }
    )
  }

  const responseHeaders = new Headers()
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name)
    if (value) responseHeaders.set(name, value)
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders })
}

export const GET = proxy
export const POST = proxy
