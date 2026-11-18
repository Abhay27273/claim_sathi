import { NextRequest, NextResponse } from "next/server";
import { gatewayHeaders, gatewayUrl } from "@/lib/gateway";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.json();

  const response = await fetch(gatewayUrl(`/cases/${id}/draft`), {
    method: "POST",
    headers: gatewayHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
