/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { PostingDetail } from "@/components/rec/PostingDetail";

export default async function Page({ params, searchParams }: PageProps<"/[locale]/rec/postings/[id]">) {
  const { id } = await params;
  const { tab } = await searchParams;
  return <PostingDetail postingId={id} initialTab={tab === "candidates" ? "candidates" : "applicants"} />;
}
