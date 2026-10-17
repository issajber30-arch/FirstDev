/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { PostingForm } from "@/components/rec/PostingForm";

export default async function Page({ params }: PageProps<"/[locale]/rec/postings/[id]/edit">) {
  const { id } = await params;
  return <PostingForm postingId={id} />;
}
