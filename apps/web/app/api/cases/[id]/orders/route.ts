import { NextRequest, NextResponse } from "next/server";
import { gatewayHeaders, gatewayUrl } from "@/lib/gateway";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { tier } = (await request.json()) as { tier: "gro_letter" | "full_ladder" };

  const form = new URLSearchParams();
  form.set("tier", tier);

  const response = await fetch(gatewayUrl(`/cases/${id}/orders`), {
    method: "POST",
    headers: gatewayHeaders({ "Content-Type": "application/x-www-form-urlencoded" }),
    body: form,
  });
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}
