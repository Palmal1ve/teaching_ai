import { useMutation } from '@tanstack/react-query'

import { api, type Revision, type Stage } from '../api/client'

const NAMES: Record<string, string> = {
  probe: 'Check the video file',
  render_deck: 'Render the slides',
  transcode_hls: 'Prepare streaming',
  extract_audio: 'Extract the audio',
  sample_frames: 'Find the slide changes',
  read_slides: 'Read text in slide images',
  transcribe: 'Transcribe the lecture',
  sync_slides: 'Sync slides to the video',
  build_passages: 'Split the transcript into passages',
  extract_knowledge: 'Extract what was taught',
  resolve_concepts: 'Merge concepts into the course',
  embed: 'Build the search index',
}

const STATES: Record<string, string> = {
  pending: 'Waiting',
  queued: 'In line',
  running: 'Running',
  done: 'Done',
  skipped: 'Not needed',
  failed: 'Failed',
  waiting_for_llm: 'Waiting for the LLM, retrying every 5 minutes',
  cancelled: 'Cancelled',
}

function StageRow({ revisionId, stage }: { revisionId: number; stage: Stage }) {
  const retry = useMutation({
    mutationFn: () => api(`/admin/revisions/${revisionId}/stages/${stage.name}/retry`, 'POST'),
  })
  return (
    <li className={`stage ${stage.status}`}>
      <span className="stage-dot" aria-hidden="true" />
      <span className="stage-name">{NAMES[stage.name] ?? stage.name}</span>
      <span className="stage-state">{STATES[stage.status] ?? stage.status}</span>
      {stage.status === 'failed' && (
        <button type="button" onClick={() => retry.mutate()} disabled={retry.isPending}>
          Retry
        </button>
      )}
      {stage.error && stage.status !== 'done' && <p className="stage-error">{stage.error}</p>}
    </li>
  )
}

export function StageList({ revision }: { revision: Revision }) {
  return (
    <ul className="stages">
      {revision.stages.map((stage) => (
        <StageRow key={stage.name} revisionId={revision.id} stage={stage} />
      ))}
    </ul>
  )
}
