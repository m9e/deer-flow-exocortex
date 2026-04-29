"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function LandingPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/workspace");
  }, [router]);

  return (
    <main className="min-h-screen bg-[var(--kz-bg)]" aria-label="Kamiwaza Flow" />
  );
}
