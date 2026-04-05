import { useState } from "react";

interface ScreenshotFrameProps {
  images: { src: string; label: string }[];
  className?: string;
}

export function ScreenshotFrame({ images, className = "" }: ScreenshotFrameProps) {
  const [activeIndex, setActiveIndex] = useState(0);

  return (
    <div className={`relative ${className}`}>
      {/* Browser Chrome */}
      <div className="rounded-xl border border-border bg-card shadow-xl overflow-hidden">
        {/* Title Bar */}
        <div className="flex items-center gap-2 px-4 py-3 bg-muted/30 border-b border-border">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-destructive/60" />
            <div className="w-3 h-3 rounded-full bg-chart-5/40" />
            <div className="w-3 h-3 rounded-full bg-primary/40" />
          </div>
          {images.length > 1 && (
            <div className="flex gap-1 ml-4">
              {images.map((img, idx) => (
                <button
                  key={img.label}
                  onClick={() => setActiveIndex(idx)}
                  className={`px-3 py-1 text-xs rounded-md transition-colors ${
                    idx === activeIndex
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted/50 text-muted-foreground hover:bg-muted"
                  }`}
                >
                  {img.label}
                </button>
              ))}
            </div>
          )}
        </div>
        {/* Screenshot */}
        <div className="relative aspect-video overflow-hidden">
          {images.map((img, idx) => (
            <img
              key={img.label}
              src={img.src}
              alt={img.label}
              className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-300 ${
                idx === activeIndex ? "opacity-100" : "opacity-0"
              }`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
