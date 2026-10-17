/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
// Shapes of the loosely typed (dict) API fields the developer screens read. Mirrors
// firstdev/schemas/cv.py, schemas/repo.py, matching/score.py and the overview route.
import type { Schemas } from "./api";

export type Level = "repo" | "assessment" | "cv";
export type SkillEntry = { skill: string; level: Level; years: number | null; sources: string[] };
export type JobStatus = "queued" | "running" | "done" | "failed";

export type Overview = {
  verified: boolean;
  cv: { id: string; status: "pending" | "parsed" | "needs_text" | "failed"; job_id: string | null } | null;
  repos: { id: string; owner: string; name: string; status: JobStatus | null; job_id: string | null }[];
  skills: SkillEntry[];
};

export type CvParse = {
  skills: { name: string; category: string; years: number | null }[];
  experience: { title: string; company: string; start: string | null; end: string | null; description: string | null }[];
  education: { institution: string; degree: string | null; field: string | null; start: string | null; end: string | null }[];
  gaps?: { start: string; end: string; months: number }[];
  summary?: string | null;
};
export type InjectionFlag = { path?: string; kind?: string; pattern?: string; excerpt?: string; [k: string]: unknown };
export type CvDoc = Omit<Schemas["CvOut"], "parse" | "injection_flags"> & {
  parse: CvParse | null;
  injection_flags: InjectionFlag[] | null;
};

export type RepoMetrics = {
  languages?: Record<string, number>;
  has_tests?: boolean;
  has_ci?: boolean;
  has_lint_config?: boolean;
  has_readme?: boolean;
  has_license?: boolean;
  commit_count?: number;
  author_count?: number;
  span_days?: number;
  total_files?: number;
};
export type RepoAssessment = {
  architecture_summary?: string;
  complexity?: number;
  best_practices?: { practice: string; observed: boolean; evidence_path: string }[];
  strengths?: string[];
  concerns?: string[];
};
export type RepoAnalysis = Omit<Schemas["RepoAnalysisOut"], "analysis"> & {
  analysis: (Omit<NonNullable<Schemas["RepoAnalysisOut"]["analysis"]>, "metrics" | "assessment"> & {
    metrics: RepoMetrics;
    assessment: RepoAssessment;
  }) | null;
};

export type Detail = { skill: string; level: Level | null; credit: number };
export type Components = {
  required_cov: number;
  optional_cov: number;
  tier_fit: number;
  required: Detail[];
  optional: Detail[];
  equivalences?: Record<string, string>;
};
export type MyMatch = {
  score: number;
  components: Components;
  feedback: { strengths?: string[]; missing_skills?: string[]; suggestions?: string[] };
  explained: boolean;
  gaps: string[];
};
