import '@uppy/core/css/style.min.css'
import '@uppy/dashboard/css/style.min.css'

import AwsS3 from '@uppy/aws-s3'
import Uppy from '@uppy/core'
import Dashboard from '@uppy/react/dashboard'
import { useEffect, useState } from 'react'

import { api, type UploadStart, type UploadState } from '../api/client'

export type UploadKind = 'video' | 'deck' | 'transcript'

const TYPES: Record<UploadKind, string[]> = {
  video: ['.mp4', '.mov', '.mkv', '.webm', '.m4v', '.avi'],
  deck: ['.pptx', '.ppt', '.pdf'],
  transcript: ['.srt', '.vtt', '.pdf'],
}

const NOTES: Record<UploadKind, string> = {
  video: 'One video, up to 3 hours and 10 GB.',
  deck: 'Optional. A .pptx, .ppt or .pdf deck.',
  transcript:
    'Optional. An .srt, .vtt or .pdf. A PDF without times is matched to the video automatically.',
}

function createUppy(
  lessonId: number,
  kind: UploadKind,
  onFinished: () => void,
  onBusy: (busy: boolean) => void,
) {
  const urls = new Map<string, Map<number, string>>()
  const partSize = { value: 64 * 1024 * 1024 }

  const remember = (start: UploadStart) => {
    partSize.value = start.part_size
    urls.set(String(start.upload_id), new Map(start.parts.map((p) => [p.part_number, p.url])))
  }

  const uppy = new Uppy({
    id: `upload-${kind}`,
    restrictions: { allowedFileTypes: TYPES[kind], maxNumberOfFiles: 1 },
    autoProceed: false,
  })
  uppy.use(AwsS3, {
    shouldUseMultipart: true,
    limit: 2,
    retryDelays: [0, 1000, 3000, 5000, 10000, 30000],
    getChunkSize: () => partSize.value,
    createMultipartUpload: async (file) => {
      const start = await api<UploadStart>(`/admin/lessons/${lessonId}/uploads`, 'POST', {
        kind,
        filename: file.name,
        size: file.size,
      })
      remember(start)
      return { uploadId: String(start.upload_id), key: String(start.upload_id) }
    },
    signPart: async (_file, { uploadId, partNumber }) => {
      if (!urls.get(uploadId)?.has(partNumber)) {
        remember(await api<UploadState>(`/admin/uploads/${uploadId}`))
      }
      return { method: 'PUT', url: urls.get(uploadId)!.get(partNumber)! }
    },
    listParts: async (_file, { uploadId }) => {
      const state = await api<UploadState>(`/admin/uploads/${uploadId}`)
      remember(state)
      return state.done.map((part) => ({
        PartNumber: part.part_number,
        Size: part.size,
        ETag: part.etag,
      }))
    },
    completeMultipartUpload: async (_file, { uploadId }) => {
      await api(`/admin/uploads/${uploadId}/complete`, 'POST')
      return {}
    },
    abortMultipartUpload: async (_file, { uploadId }) => {
      if (uploadId) await api(`/admin/uploads/${uploadId}`, 'DELETE')
    },
  })
  uppy.on('upload', () => onBusy(true))
  uppy.on('cancel-all', () => onBusy(false))
  uppy.on('complete', () => {
    onBusy(false)
    onFinished()
  })
  return uppy
}

type Props = {
  lessonId: number
  kind: UploadKind
  onFinished: () => void
  onBusy: (busy: boolean) => void
}

export function Uploader({ lessonId, kind, onFinished, onBusy }: Props) {
  const [uppy] = useState(() => createUppy(lessonId, kind, onFinished, onBusy))
  useEffect(() => () => uppy.destroy(), [uppy])
  return (
    <Dashboard
      uppy={uppy}
      height={220}
      width="100%"
      proudlyDisplayPoweredByUppy={false}
      note={NOTES[kind]}
    />
  )
}
