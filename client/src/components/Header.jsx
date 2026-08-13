import React from 'react';
import { ShieldCheck, BarChart2, Github } from 'lucide-react';

export default function Header({ onOpenMetrics }) {
  return (
    <header className="header">
      <div className="logo-group">
        <div className="logo-icon">
          <ShieldCheck size={26} />
        </div>
        <div>
          <div className="logo-title">PII Shield</div>
          <div className="logo-subtitle">Microsoft Presidio Hybrid Redaction for Word Documents</div>
        </div>
      </div>

      <div className="nav-actions">
        <button className="btn btn-outline" onClick={onOpenMetrics}>
          <BarChart2 size={16} />
          Evaluation Metrics
        </button>
        <a 
          href="https://github.com/Ankii04/PII-Redaction-Tool" 
          target="_blank" 
          rel="noopener noreferrer"
          className="btn btn-outline"
        >
          <Github size={16} />
          GitHub
        </a>
      </div>
    </header>
  );
}
