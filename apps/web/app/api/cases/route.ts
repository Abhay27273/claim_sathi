import { NextRequest, NextResponse } from "next/server";
import { gatewayHeaders, gatewayUrl } from "@/lib/gateway";

// Proxies the multipart upload straight through to the gateway's /cases.
// Don't set a Content-Type header manually here -- fetch sets the correct
// multipart boundary itself when the body is a FormData instance; overriding
// it would break the upload.
export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const response = await fetch(gatewayUrl("/cases"), {
    method: "POST",
    headers: gatewayHeaders(),
    body: formData,
  });
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
