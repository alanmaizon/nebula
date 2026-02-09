import React, { useCallback } from 'react';
import { FileArtifact } from '../types';
import { Upload, X, FileText } from 'lucide-react';

interface FileUploadProps {
  files: FileArtifact[];
  onFilesChange: (files: FileArtifact[]) => void;
}

export const FileUpload: React.FC<FileUploadProps> = ({ files, onFilesChange }) => {
  const handleFileChange = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files) {
      const newFiles: FileArtifact[] = [];
      const fileList = Array.from(event.target.files);

      for (const file of fileList) {
        try {
          const text = await file.text();
          newFiles.push({
            name: file.name,
            content: text,
            size: file.size,
          });
        } catch (err) {
          console.error(`Failed to read file ${file.name}`, err);
        }
      }
      
      onFilesChange([...files, ...newFiles]);
      event.target.value = '';
    }
  }, [files, onFilesChange]);

  const removeFile = useCallback((indexToRemove: number) => {
    onFilesChange(files.filter((_, index) => index !== indexToRemove));
  }, [files, onFilesChange]);

  return (
    <div className="space-y-4">
      <div className="group relative border border-dashed border-zinc-700 rounded-2xl p-8 hover:bg-zinc-800/30 hover:border-cyan-500/50 transition-all duration-300 text-center cursor-pointer overflow-hidden">
        {/* Glow effect on hover */}
        <div className="absolute inset-0 bg-cyan-500/5 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none blur-xl"></div>
        
        <input
          type="file"
          multiple
          onChange={handleFileChange}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
        />
        <div className="relative z-0 flex flex-col items-center justify-center space-y-3 pointer-events-none">
          <div className="p-3 bg-zinc-900 rounded-full border border-zinc-700 group-hover:border-cyan-500/50 group-hover:shadow-[0_0_15px_rgba(6,182,212,0.2)] transition-all duration-300">
            <Upload className="w-6 h-6 text-zinc-400 group-hover:text-cyan-400" />
          </div>
          <p className="text-sm text-zinc-300 font-medium group-hover:text-cyan-100 transition-colors">
            Drop artifacts here
          </p>
          <p className="text-xs text-zinc-500">Log files, config, JSON, YAML</p>
        </div>
      </div>

      {files.length > 0 && (
        <div className="grid grid-cols-1 gap-2">
          {files.map((file, index) => (
            <div key={`${file.name}-${index}`} className="flex items-center justify-between bg-zinc-900/60 backdrop-blur-sm p-3 rounded-xl border border-white/5 shadow-sm group hover:border-white/10 transition-colors">
              <div className="flex items-center space-x-3 overflow-hidden">
                <FileText className="w-4 h-4 text-cyan-500 flex-shrink-0" />
                <span className="text-sm font-medium text-zinc-300 truncate group-hover:text-white transition-colors">{file.name}</span>
                <span className="text-xs text-zinc-600 flex-shrink-0">({(file.size / 1024).toFixed(1)} KB)</span>
              </div>
              <button
                onClick={() => removeFile(index)}
                className="p-1.5 hover:bg-red-500/10 text-zinc-500 hover:text-red-400 rounded-lg transition-colors"
                title="Remove file"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
