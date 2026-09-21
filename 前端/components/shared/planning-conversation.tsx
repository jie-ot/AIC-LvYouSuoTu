"use client";

import { useEffect, useRef } from "react";
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  Send,
  WandSparkles,
} from "lucide-react";
import type {
  PlanningChecklistItem,
  PlanningModel,
  PlanningPhase,
} from "@/types";

export interface PlanningConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  planningModel?: PlanningModel;
}

interface PlanningConversationProps {
  messages: PlanningConversationMessage[];
  phase: Exclude<PlanningPhase, "completed">;
  checklist: PlanningChecklistItem[];
  value: string;
  busy: boolean;
  confirmationReady: boolean;
  onChange: (value: string) => void;
  onSend: () => void;
  onConfirm: () => void;
}

export function PlanningConversation({
  messages,
  phase,
  checklist,
  value,
  busy,
  confirmationReady,
  onChange,
  onSend,
  onConfirm,
}: PlanningConversationProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (messages.length > 1)
      bottomRef.current?.scrollIntoView({
        block: "end",
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
      });
  }, [busy, messages, phase]);
  return (
    <div className="planning-chat" data-testid="planning-conversation">
      <div className="planning-chat-scroll">
        <header className="planning-intro">
          <ol aria-label="规划步骤">
            {["填写需求", "确认信息", "生成行程"].map((label, index) => (
              <li
                key={label}
                className={
                  index === (phase === "confirming" ? 1 : 0) ? "is-active" : ""
                }
              >
                <span>0{index + 1}</span>
                {label}
              </li>
            ))}
          </ol>
        </header>
        <div className="chat-messages" aria-live="polite">
          {messages.map((message) => (
            <div key={message.id} className={`chat-message is-${message.role}`}>
              {message.role === "assistant" && (
                <span className="chat-author">
                  行程助手
                </span>
              )}
              <p>{message.content}</p>
            </div>
          ))}
          {busy && (
            <div className="chat-thinking" data-testid="planning-thinking">
              <i />
              <i />
              <i />
              <span>正在整理</span>
            </div>
          )}
        </div>
        {messages.length === 1 && (
          <div className="planning-starters">
            {[
              "10 月去杭州，3 天，两个人",
              "带长辈去北京，尽量少走路",
              "从武汉出发，高铁优先，预算 3000 元",
              "周末去上海，想看展览和逛街区",
            ].map((text) => (
              <button
                key={text}
                onClick={() => {
                  onChange(text);
                  inputRef.current?.focus();
                }}
              >
                {text}
                <ArrowUpRight size={14} />
              </button>
            ))}
          </div>
        )}
        {phase === "confirming" && checklist.length > 0 && (
          <section
            className="planning-checklist"
            data-testid="planning-checklist"
          >
            <header>
              <h3>确认旅行需求</h3>
            </header>
            <dl>
              {checklist.map((item) => (
                <div
                  key={item.key}
                  className={item.status === "missing" ? "is-missing" : ""}
                >
                  <dt>
                    {item.status === "ready" ? (
                      <Check size={13} />
                    ) : item.status === "assumed" ? (
                      <WandSparkles size={13} />
                    ) : (
                      <CircleAlert size={13} />
                    )}{" "}
                    {item.label}
                  </dt>
                  <dd>{item.value}</dd>
                </div>
              ))}
            </dl>
            <button
              className="primary-action"
              onClick={onConfirm}
              disabled={busy || !confirmationReady}
              data-testid="confirm-and-generate"
            >
              {confirmationReady ? "确认，生成行程" : "正在更新清单"}
              <ArrowUpRight size={18} />
            </button>
            <button
              className="checklist-edit"
              onClick={() => inputRef.current?.focus()}
            >
              继续补充
            </button>
          </section>
        )}
        <div ref={bottomRef} />
      </div>
      <footer className="chat-composer">
        <div>
          <textarea
            ref={inputRef}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                if (!busy && value.trim()) onSend();
              }
            }}
            disabled={busy}
            placeholder={
              phase === "confirming"
                ? "还有什么想调整的？"
                : "例如：10 月去杭州，3 天，两个人"
            }
            rows={2}
            aria-label="旅行需求"
            data-testid="planning-chat-input"
          />
          <button
            type="button"
            onClick={onSend}
            disabled={busy || !value.trim()}
            aria-label="发送旅行需求"
            data-testid="planning-chat-send"
          >
            <Send size={18} />
          </button>
        </div>
      </footer>
    </div>
  );
}
