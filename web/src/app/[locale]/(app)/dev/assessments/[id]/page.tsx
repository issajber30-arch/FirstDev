/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { AssessmentRun } from "@/components/assess/AssessmentRun";

export default async function Page({ params }: PageProps<"/[locale]/dev/assessments/[id]">) {
  const { id } = await params;
  return <AssessmentRun id={id} />;
}
