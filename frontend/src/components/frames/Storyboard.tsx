import { useState } from 'react'
import { useProjectStore } from '../../store/projectStore'
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  horizontalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { API_BASE } from '../../api/config'

function SortableSlide({ id, index, isActive, isMeme, isAppAd, frameUrl, memeCategory, onClick, onDelete }: {
  id: string
  index: number
  isActive: boolean
  isMeme: boolean
  isAppAd: boolean
  frameUrl: string | null
  memeCategory: string | null
  onClick: () => void
  onDelete: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id })
  const style = { transform: CSS.Transform.toString(transform), transition }
  const [confirmDelete, setConfirmDelete] = useState(false)

  const isVideo = frameUrl?.endsWith('.mp4') || frameUrl?.endsWith('.mov')

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (confirmDelete) {
      onDelete()
    } else {
      setConfirmDelete(true)
      // Auto-cancel confirmation after 2 seconds
      setTimeout(() => setConfirmDelete(false), 2000)
    }
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={onClick}
      className={`group w-16 h-28 rounded-lg flex-shrink-0 flex flex-col items-center justify-center text-xs font-mono cursor-pointer transition-all overflow-hidden relative ${
        isActive
          ? isAppAd
            ? 'border-2 border-green-400 ring-1 ring-green-400/40'
            : isMeme
              ? 'border-2 border-amber-400 ring-1 ring-amber-400/40'
              : 'border-2 border-blue-500 ring-1 ring-blue-500/40'
          : isAppAd
            ? 'border border-green-700/60 hover:border-green-500'
            : isMeme
              ? 'border border-amber-700/60 hover:border-amber-500'
              : 'border border-zinc-700 hover:border-zinc-500'
      } ${isAppAd ? 'bg-zinc-900' : isMeme ? 'bg-zinc-900' : 'bg-zinc-800'}`}
    >
      {/* Meme thumbnail */}
      {isMeme && frameUrl && !isVideo && (
        <img
          src={`${API_BASE}${frameUrl}`}
          alt=""
          className="absolute inset-0 w-full h-full object-contain opacity-70"
          draggable={false}
        />
      )}
      {isMeme && frameUrl && isVideo && (
        <div className="absolute inset-0 bg-purple-900/40 flex items-center justify-center">
          <span className="text-lg">▶</span>
        </div>
      )}

      {/* Delete button — visible on hover or when awaiting confirmation */}
      <button
        className={`absolute top-1 right-1 z-20 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold leading-none transition-all
          ${confirmDelete
            ? 'bg-red-500 text-white opacity-100 scale-110'
            : 'bg-black/60 text-zinc-300 opacity-0 group-hover:opacity-100 hover:bg-red-500 hover:text-white'
          }`}
        title={confirmDelete ? 'Nogmaals klikken om te verwijderen' : 'Frame verwijderen'}
        /* Stop pointer-down so dnd-kit never starts a drag from this button */
        onPointerDown={(e) => e.stopPropagation()}
        onClick={handleDeleteClick}
      >
        {confirmDelete ? '!' : '×'}
      </button>

      {/* Overlay content */}
      <div className="relative z-10 flex flex-col items-center gap-0.5">
        {/* Type badge */}
        <span className={`text-[8px] font-bold px-1 py-0.5 rounded ${
          isAppAd
            ? 'bg-green-600/80 text-white'
            : isMeme
              ? 'bg-amber-500/80 text-black'
              : 'bg-blue-600/70 text-white'
        }`}>
          {isAppAd ? 'APP AD' : isMeme ? 'MEME' : 'DM'}
        </span>
        {/* Meme category sub-label */}
        {isMeme && memeCategory && (
          <span className="text-[7px] font-bold px-1 py-0.5 rounded bg-black/60 text-amber-300 leading-none max-w-[56px] truncate text-center">
            {memeCategory}
          </span>
        )}
        {/* Slide number */}
        <span className={`font-bold ${
          isAppAd
            ? (isActive ? 'text-green-300' : 'text-green-600')
            : isMeme
              ? (isActive ? 'text-amber-300' : 'text-amber-600')
              : (isActive ? 'text-blue-300' : 'text-zinc-400')
        }`}>
          {index + 1}
        </span>
        {/* Empty slot indicator */}
        {isAppAd && !frameUrl && (
          <span className="text-green-700 text-[10px]">📱 add</span>
        )}
        {isMeme && !frameUrl && (
          <span className="text-amber-700 text-[10px]">✚ meme</span>
        )}
      </div>
    </div>
  )
}

export default function Storyboard() {
  const { slides, activeSlideId, selectSlide, addSlide, addMemeSlide, reorderSlides, removeSlide } = useProjectStore()

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  )

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = slides.findIndex((s) => s.id === active.id)
    const newIndex = slides.findIndex((s) => s.id === over.id)
    const newOrder = [...slides.map((s) => s.id)]
    newOrder.splice(oldIndex, 1)
    newOrder.splice(newIndex, 0, active.id as string)
    reorderSlides(newOrder)
  }

  const handleDelete = async (slideId: string) => {
    await removeSlide(slideId)
    // After deletion, select the nearest remaining slide
    const remaining = slides.filter((s) => s.id !== slideId)
    if (remaining.length > 0) {
      const deletedIndex = slides.findIndex((s) => s.id === slideId)
      const nextSlide = remaining[Math.min(deletedIndex, remaining.length - 1)]
      selectSlide(nextSlide.id)
    }
  }

  return (
    <div className="h-40 border-t border-zinc-800 bg-zinc-900/50 flex-shrink-0">
      <div className="h-full flex items-center px-4 gap-3 overflow-x-auto">
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={slides.map((s) => s.id)} strategy={horizontalListSortingStrategy}>
            {slides.map((slide, i) => (
              <SortableSlide
                key={slide.id}
                id={slide.id}
                index={i}
                isActive={slide.id === activeSlideId}
                isMeme={slide.frame_type === 'meme'}
                isAppAd={slide.frame_type === 'app_ad'}
                frameUrl={slide.frame_url ?? null}
                memeCategory={slide.meme_category ?? null}
                onClick={() => selectSlide(slide.id)}
                onDelete={() => handleDelete(slide.id)}
              />
            ))}
          </SortableContext>
        </DndContext>

        {/* Add slide buttons */}
        <div className="flex flex-col gap-1.5 flex-shrink-0">
          <button
            onClick={addSlide}
            title="Add DM slide"
            className="w-16 h-[52px] rounded-lg border-2 border-dashed border-blue-700/60 flex flex-col items-center justify-center gap-0.5 text-blue-500 hover:border-blue-500 hover:text-blue-300 hover:bg-blue-500/5 transition-colors"
          >
            <span className="text-base leading-none">+</span>
            <span className="text-[8px] font-bold">DM</span>
          </button>
          <button
            onClick={addMemeSlide}
            title="Add meme slide"
            className="w-16 h-[52px] rounded-lg border-2 border-dashed border-amber-700/60 flex flex-col items-center justify-center gap-0.5 text-amber-600 hover:border-amber-500 hover:text-amber-400 hover:bg-amber-500/5 transition-colors"
          >
            <span className="text-base leading-none">+</span>
            <span className="text-[8px] font-bold">MEME</span>
          </button>
        </div>
      </div>
    </div>
  )
}
