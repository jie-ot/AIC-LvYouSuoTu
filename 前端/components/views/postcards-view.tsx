"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Images, Plus, Trash2 } from "lucide-react";
import { useApp } from "@/components/shared/app-context";
import { BottomNav } from "@/components/shared/bottom-nav";
import { ActionMenu } from "@/components/shared/action-menu";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import {
  PLACEHOLDER_IMAGE,
  handleImageError,
  resolveAssetUrl,
} from "@/lib/asset";
import { displayPlace } from "@/lib/place";
import type { PostcardGroup } from "@/types";
export function PostcardsView() {
  const { postcardGroups, trips, navigate, deletePostcardGroup, deletingId } =
    useApp();
  const [pending, setPending] = useState<PostcardGroup | null>(null);
  const placeOf = (group: PostcardGroup) =>
    displayPlace(group.location, trips.find((trip) => trip.id === group.tripId)?.title);
  return (
    <div className="app-page archive-page">
      <header className="collection-header">
        <div className="brand-mark">旅有所图</div>
        <div className="collection-title-row">
          <h1>明信片</h1>
          <Link href="/create?mode=postcard" className="primary-quiet-button"><Plus size={17} />制作</Link>
        </div>
        <p className="collection-count">{postcardGroups.reduce((n, g) => n + g.postcards.length, 0)} 张</p>
      </header>
      <main className="archive-scroll">
        {postcardGroups.length ? (
          <div className="postcard-archive">
            {postcardGroups.map((group) => (
              <article key={group.id}>
                <button
                  className="postcard-archive-open"
                  onClick={() =>
                    navigate({ page: "postcard-collection", groupId: group.id })
                  }
                >
                  <div className="postcard-archive-photo">
                    <img
                      src={
                        resolveAssetUrl(group.coverImage) || PLACEHOLDER_IMAGE
                      }
                      alt={placeOf(group)}
                      loading="lazy"
                      onError={handleImageError}
                    />
                    <span>{group.postcards.length} 张</span>
                  </div>
                  <div className="postcard-archive-caption">
                    <h3>{placeOf(group)}</h3>
                    <span>{group.dateLabel}</span>
                    <ArrowUpRight size={18} />
                  </div>
                </button>
                <div className="archive-menu">
                  <ActionMenu
                    items={[
                      {
                        label: "删除",
                        icon: <Trash2 size={16} />,
                        onClick: () => setPending(group),
                        danger: true,
                      },
                    ]}
                  />
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<Images size={28} />}
            title="还没有明信片"
          >
            <Link href="/create?mode=postcard" className="primary-action">
              上传照片
            </Link>
          </EmptyState>
        )}
      </main>
      <ConfirmDialog
        open={!!pending}
        title="删除这组明信片？"
        description={
          pending
            ? `${placeOf(pending)} · ${pending.postcards.length} 张明信片`
            : ""
        }
        onClose={() => setPending(null)}
        actions={[
          {
            label: deletingId === pending?.id ? "删除中…" : "删除",
            variant: "danger",
            onClick: () => {
              if (pending && deletingId !== pending.id)
                void deletePostcardGroup(pending.id).then(() =>
                  setPending(null),
                );
            },
          },
          { label: "取消", variant: "ghost", onClick: () => setPending(null) },
        ]}
      />
      <BottomNav />
    </div>
  );
}
