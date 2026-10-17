/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { MatchDetail } from "@/components/dev/MatchDetail";

export default async function Page({ params }: PageProps<"/[locale]/dev/jobs/[postingId]">) {
  const { postingId } = await params;
  return <MatchDetail postingId={postingId} />;
}
