import { PipelineMonitor } from "@/components/pipeline-monitor";
import { getPipelineRuns } from "@/lib/api-pipeline";

export default async function PipelineAdminPage() {
  const pipelineState = await getPipelineRuns(20);
  return <PipelineMonitor pipelineState={pipelineState} />;
}
