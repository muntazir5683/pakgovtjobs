"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { API_URL } from "@/lib/api";
import { ADMIN_COOKIE, adminFetch } from "@/lib/admin";

export type LoginState = { error?: string };

export async function login(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const password = String(formData.get("password") ?? "");
  if (!password) return { error: "Enter the admin password." };

  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/admin/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
      cache: "no-store",
    });
  } catch {
    return { error: "Backend is unreachable." };
  }
  if (res.status === 401) return { error: "Wrong password." };
  if (!res.ok) return { error: `Login failed (${res.status}).` };

  const { token, expires_in } = (await res.json()) as { token: string; expires_in: number };
  (await cookies()).set(ADMIN_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/admin",
    maxAge: expires_in,
  });
  revalidatePath("/admin");
  return {};
}

export async function logout(): Promise<void> {
  (await cookies()).delete({ name: ADMIN_COOKIE, path: "/admin" });
  revalidatePath("/admin");
}

export async function runCrawler(): Promise<void> {
  await adminFetch("/api/admin/crawl", { method: "POST" });
  revalidatePath("/admin");
}

export async function expireNow(): Promise<void> {
  await adminFetch("/api/admin/expire", { method: "POST" });
  revalidatePath("/admin");
}

export async function toggleSource(formData: FormData): Promise<void> {
  const id = Number(formData.get("id"));
  if (Number.isInteger(id)) await adminFetch(`/api/admin/sources/${id}/toggle`, { method: "POST" });
  revalidatePath("/admin");
}
