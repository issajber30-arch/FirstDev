/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { AssessmentReport } from "@/components/assess/AssessmentReport";

export default async function Page({ params }: PageProps<"/[locale]/dev/assessments/[id]/report">) {
  const { id } = await params;
  return <AssessmentReport id={id} />;
}
