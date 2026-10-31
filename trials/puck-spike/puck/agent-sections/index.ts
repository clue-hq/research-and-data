// Written by write_section (tools.py). Every site's agent-written sections.
import type { AgentSectionModule } from "../agent-kit";
import * as s0 from "./agent-cl3/AnalyticsFeatures";
import * as s1 from "./agent-cl3/AudienceBand";
import * as s2 from "./agent-cl3/PhotoHero";
import * as s3 from "./agent-cl3/ProviderInsights";
import * as s4 from "./agent-cl3/SplitCta";
import * as s5 from "./agent-e5/AnalysisSteps";
import * as s6 from "./agent-e5b/AnalysisSteps";
export const AGENT_SECTIONS: Record<string, Record<string, AgentSectionModule>> = {
  "agent-cl3": { "AnalyticsFeatures": s0 as unknown as AgentSectionModule, "AudienceBand": s1 as unknown as AgentSectionModule, "PhotoHero": s2 as unknown as AgentSectionModule, "ProviderInsights": s3 as unknown as AgentSectionModule, "SplitCta": s4 as unknown as AgentSectionModule },
  "agent-e5": { "AnalysisSteps": s5 as unknown as AgentSectionModule },
  "agent-e5b": { "AnalysisSteps": s6 as unknown as AgentSectionModule },
};
