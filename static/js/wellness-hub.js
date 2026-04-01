(() => {
  const pageId = document.body.dataset.page;

  if (!window.HealHub) return;

  const { api, setBusy } = window.HealHub;

  function feedbackTarget() {
    return document.querySelector("[data-page-feedback]");
  }

  function setPageFeedback(message, tone = "neutral") {
    const target = feedbackTarget();
    if (!target) return;
    target.textContent = message;
    target.classList.remove("status-neutral", "status-stable", "status-warning", "status-critical");
    target.classList.add(`status-${tone}`);
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function initMoviesPage() {
    if (pageId !== "movies") return;

    document.addEventListener("click", async (event) => {
      const actionButton = event.target.closest("[data-movie-action]");
      if (actionButton) {
        const movieId = actionButton.dataset.movieId;
        const action = actionButton.dataset.movieAction;
        const card = actionButton.closest("[data-movie-card]");
        const watchedButton = card?.querySelector('[data-movie-action="watched"]');
        const wantButton = card?.querySelector('[data-movie-action="want_to_watch"]');
        const favoriteButton = card?.querySelector('[data-movie-action="favorite"]');

        try {
          setBusy(actionButton, true, "Saving...");
          await api("/api/movie-action", {
            method: "POST",
            body: JSON.stringify({ movie_id: movieId, action }),
          });

          if (action === "watched" && watchedButton) {
            watchedButton.dataset.defaultLabel = "Watched";
            watchedButton.textContent = "Watched";
          }
          if (action === "want_to_watch" && wantButton) {
            wantButton.dataset.defaultLabel = "Saved";
            wantButton.textContent = "Saved";
          }
          if (action === "favorite") {
            if (favoriteButton) {
              favoriteButton.dataset.defaultLabel = "Favorited";
              favoriteButton.textContent = "Favorited";
            }
            if (watchedButton) {
              watchedButton.dataset.defaultLabel = "Watched";
              watchedButton.textContent = "Watched";
            }
          }

          setPageFeedback("Your story journey has been updated.", "stable");
        } catch (error) {
          setPageFeedback(error.message || "We could not save that action.", "warning");
        } finally {
          setBusy(actionButton, false, "Saving...");
        }
        return;
      }

      const saveInterestsButton = event.target.closest("[data-save-interests]");
      if (!saveInterestsButton) return;

      const selected = Array.from(document.querySelectorAll("[data-interest-grid] input:checked")).map(
        (input) => input.value,
      );

      try {
        setBusy(saveInterestsButton, true, "Saving...");
        await api("/api/movie-interests", {
          method: "POST",
          body: JSON.stringify({ interests: selected }),
        });
        setPageFeedback("Saved your healing-story interests.", "stable");
      } catch (error) {
        setPageFeedback(error.message || "We could not save your interests.", "warning");
      } finally {
        setBusy(saveInterestsButton, false, "Saving...");
      }
    });
  }

  function initTherapistsPage() {
    if (pageId !== "therapists") return;

    document.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-book-therapist]");
      if (!button) return;

      const card = button.closest("[data-therapist-card]");
      const therapistId = button.dataset.therapistId;
      const date = card?.querySelector("[data-booking-date]")?.value || "";
      const time = card?.querySelector("[data-booking-time]")?.value || "";
      const notes = card?.querySelector("[data-booking-notes]")?.value || "";

      try {
        setBusy(button, true, "Booking...");
        await api("/api/book-therapist", {
          method: "POST",
          body: JSON.stringify({ therapist_id: therapistId, date, time, notes }),
        });
        button.dataset.defaultLabel = "Booked";
        button.textContent = "Booked";
        setPageFeedback("Your appointment has been added to the demo schedule.", "stable");
      } catch (error) {
        setPageFeedback(error.message || "Booking could not be completed.", "warning");
      } finally {
        setBusy(button, false, "Booking...");
      }
    });
  }

  function initCommunityComposer() {
    const textarea = document.querySelector("[data-community-post]");
    const counter = document.querySelector("[data-community-count]");
    const kindSelect = document.querySelector("[data-community-kind]");
    const moodSelect = document.querySelector("[data-community-mood]");
    const groupSelect = document.querySelector("[data-community-group]");
    const anonymousToggle = document.querySelector("[data-community-anonymous]");
    const draftStatus = document.querySelector("[data-draft-status]");
    const clearDraftButton = document.querySelector("[data-clear-community-draft]");
    if (!textarea || !counter) return;

    const sessionUser = window.HealHubSession?.user?.username || "guest";
    const draftKey = `healhub.communityDraft.${sessionUser}`;
    const normalizeKindValue = (value) => {
      if (value === "reflection") return "discussion";
      if (value === "question") return "help";
      return value;
    };

    const updateCounter = () => {
      counter.textContent = `${textarea.value.length} / ${textarea.maxLength || 420}`;
    };

    const setDraftStatus = (message, tone = "neutral") => {
      if (!draftStatus) return;
      draftStatus.textContent = message;
      draftStatus.classList.remove("status-neutral", "status-stable", "status-warning");
      draftStatus.classList.add(`status-${tone}`);
    };

    const persistDraft = () => {
      const payload = {
        content: textarea.value || "",
        kind: normalizeKindValue(kindSelect?.value || "discussion"),
        mood: moodSelect?.value || "steady",
        group: groupSelect?.value || "grp-006",
        anonymous: Boolean(anonymousToggle?.checked),
        promptLabel: textarea.dataset.promptLabel || "",
      };
      try {
        localStorage.setItem(draftKey, JSON.stringify(payload));
        if (payload.content.trim()) {
          setDraftStatus("Draft saved", "stable");
        } else {
          setDraftStatus("Draft is empty", "neutral");
        }
      } catch (_error) {
        setDraftStatus("Draft unavailable", "warning");
      }
    };

    const restoreDraft = () => {
      try {
        const raw = localStorage.getItem(draftKey);
        if (!raw) {
          setDraftStatus("Draft not saved yet", "neutral");
          return;
        }
        const draft = JSON.parse(raw);
        if (typeof draft.content === "string" && !textarea.value.trim()) {
          textarea.value = draft.content;
        }
        if (kindSelect && typeof draft.kind === "string") {
          kindSelect.value = normalizeKindValue(draft.kind);
        }
        if (moodSelect && typeof draft.mood === "string") {
          moodSelect.value = draft.mood;
        }
        if (groupSelect && typeof draft.group === "string") {
          groupSelect.value = draft.group;
        }
        if (anonymousToggle) {
          anonymousToggle.checked = Boolean(draft.anonymous);
        }
        textarea.dataset.promptLabel = typeof draft.promptLabel === "string" ? draft.promptLabel : "";
        if (textarea.value.trim()) {
          setDraftStatus("Draft restored", "stable");
        } else {
          setDraftStatus("Draft not saved yet", "neutral");
        }
      } catch (_error) {
        setDraftStatus("Draft unavailable", "warning");
      }
    };

    const clearDraft = () => {
      textarea.value = "";
      textarea.dataset.promptLabel = "";
      if (anonymousToggle) anonymousToggle.checked = false;
      try {
        localStorage.removeItem(draftKey);
      } catch (_error) {
        // no-op
      }
      updateCounter();
      setDraftStatus("Draft cleared", "neutral");
    };

    textarea.addEventListener("input", updateCounter);
    textarea.addEventListener("input", persistDraft);
    kindSelect?.addEventListener("change", persistDraft);
    moodSelect?.addEventListener("change", persistDraft);
    groupSelect?.addEventListener("change", persistDraft);
    anonymousToggle?.addEventListener("change", persistDraft);
    clearDraftButton?.addEventListener("click", clearDraft);

    restoreDraft();
    updateCounter();

    document.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-community-prompt]");
      if (!chip) return;
      textarea.value = chip.dataset.promptText || "";
      textarea.dataset.promptLabel = chip.dataset.promptLabel || "";
      if (kindSelect && chip.dataset.promptKind) {
        kindSelect.value = chip.dataset.promptKind;
      }
      if (moodSelect && chip.dataset.promptMood) {
        moodSelect.value = chip.dataset.promptMood;
      }
      textarea.focus();
      updateCounter();
      persistDraft();
      setPageFeedback("Prompt loaded. Make it your own before posting.", "stable");
    });

    window.HealHubCommunityDraft = {
      clear: clearDraft,
      key: draftKey,
    };
  }

  function createReplyCard(reply) {
    const article = document.createElement("article");
    article.className = "reply-card";
    article.innerHTML = `
      <div class="community-reply-head">
        <span class="story-card-icon community-reply-avatar">${escapeHtml(reply.avatar || "💬")}</span>
        <div>
          <strong>${escapeHtml(reply.author || "Heal Hub Member")}</strong>
          <small>${escapeHtml(reply.timestamp || "Now")}</small>
        </div>
      </div>
      <p>${escapeHtml(reply.content || "")}</p>
    `;
    return article;
  }

  function updateRelationshipState(container, state) {
    if (!container) return;
    const statusChip = container.querySelector(".status-chip");
    const actionButton = container.querySelector("[data-connect-user], [data-accept-connection]");

    if (statusChip) {
      statusChip.classList.remove("status-warning", "status-neutral", "status-stable");
      if (state === "connected") {
        statusChip.textContent = "Connected";
        statusChip.classList.add("status-stable");
      } else if (state === "request_sent") {
        statusChip.textContent = "Request sent";
        statusChip.classList.add("status-neutral");
      }
    }

    if (actionButton) {
      if (state === "connected") {
        actionButton.textContent = "Connected";
        actionButton.disabled = true;
      } else if (state === "request_sent") {
        actionButton.textContent = "Request sent";
        actionButton.disabled = true;
      }
    }
  }

  function initCommunityPage() {
    if (pageId !== "community") return;

    initCommunityComposer();

    document.addEventListener("click", async (event) => {
      const joinButton = event.target.closest("[data-join-community]");
      if (joinButton) {
        try {
          setBusy(joinButton, true, "Joining...");
          await api("/api/join-community", {
            method: "POST",
            body: JSON.stringify({ group_id: joinButton.dataset.groupId }),
          });
          joinButton.textContent = "Joined";
          joinButton.disabled = true;
          setPageFeedback("You joined a new support circle.", "stable");
        } catch (error) {
          setPageFeedback(error.message || "We could not join that circle.", "warning");
        } finally {
          if (!joinButton.disabled) {
            setBusy(joinButton, false, "Joining...");
          }
        }
        return;
      }

      const connectButton = event.target.closest("[data-connect-user]");
      if (connectButton) {
        try {
          setBusy(connectButton, true, "Sending...");
          await api("/api/send-connection-request", {
            method: "POST",
            body: JSON.stringify({ target_username: connectButton.dataset.username }),
          });
          updateRelationshipState(
            connectButton.closest(".community-person-card") || connectButton.closest(".community-request-card"),
            "request_sent",
          );
          setPageFeedback("Connection request sent.", "stable");
        } catch (error) {
          setPageFeedback(error.message || "Connection request could not be sent.", "warning");
        } finally {
          if (!connectButton.disabled) {
            setBusy(connectButton, false, "Sending...");
          }
        }
        return;
      }

      const acceptButton = event.target.closest("[data-accept-connection]");
      if (acceptButton) {
        try {
          setBusy(acceptButton, true, "Connecting...");
          await api("/api/accept-connection", {
            method: "POST",
            body: JSON.stringify({ from_username: acceptButton.dataset.username }),
          });
          updateRelationshipState(
            acceptButton.closest(".community-person-card") || acceptButton.closest(".community-request-card"),
            "connected",
          );
          setPageFeedback("Connection accepted.", "stable");
        } catch (error) {
          setPageFeedback(error.message || "Connection could not be accepted.", "warning");
        } finally {
          if (!acceptButton.disabled) {
            setBusy(acceptButton, false, "Connecting...");
          }
        }
        return;
      }

      const postButton = event.target.closest("[data-submit-post]");
      if (postButton) {
        const groupId = document.querySelector("[data-community-group]")?.value || "grp-006";
        const contentField = document.querySelector("[data-community-post]");
        const kind = document.querySelector("[data-community-kind]")?.value || "discussion";
        const mood = document.querySelector("[data-community-mood]")?.value || "steady";
        const anonymous = document.querySelector("[data-community-anonymous]")?.checked || false;
        const content = contentField?.value.trim() || "";
        const promptLabel = contentField?.dataset.promptLabel || "";
        if (!content) {
          setPageFeedback("Write a few words before posting.", "warning");
          return;
        }

        try {
          setBusy(postButton, true, "Posting...");
          await api("/api/community-post", {
            method: "POST",
            body: JSON.stringify({
              group_id: groupId,
              content,
              post_kind: kind,
              mood,
              anonymous,
              prompt_label: promptLabel,
            }),
          });
          window.HealHubCommunityDraft?.clear?.();
          window.location.reload();
        } catch (error) {
          setPageFeedback(error.message || "Post could not be shared.", "warning");
        } finally {
          setBusy(postButton, false, "Posting...");
        }
        return;
      }

      const reactionButton = event.target.closest("[data-support-post]");
      if (reactionButton) {
        const card = reactionButton.closest("[data-post-card]");
        if (!card) return;
        const reactionType = reactionButton.dataset.reactionType || "support";
        reactionButton.disabled = true;
        try {
          const payload = await api("/api/community-react", {
            method: "POST",
            body: JSON.stringify({
              post_id: reactionButton.dataset.postId,
              reaction_type: reactionType,
            }),
          });
          Object.entries(payload.reactions || {}).forEach(([key, value]) => {
            const countEl = card.querySelector(`[data-reaction-count="${key}"]`);
            if (countEl) countEl.textContent = String(value);
          });
          const totalEl = card.querySelector("[data-reaction-total]");
          if (totalEl) totalEl.textContent = String(payload.reaction_total || 0);
          reactionButton.classList.add("is-sent");
          window.setTimeout(() => reactionButton.classList.remove("is-sent"), 1200);
          setPageFeedback("Reaction sent.", "stable");
        } catch (error) {
          setPageFeedback(error.message || "Support could not be sent.", "warning");
        } finally {
          reactionButton.disabled = false;
        }
        return;
      }

      const bookmarkButton = event.target.closest("[data-bookmark-post]");
      if (bookmarkButton) {
        const card = bookmarkButton.closest("[data-post-card]");
        try {
          setBusy(bookmarkButton, true, "Saving...");
          const payload = await api("/api/community-bookmark", {
            method: "POST",
            body: JSON.stringify({ post_id: bookmarkButton.dataset.postId }),
          });
          const countEl = card?.querySelector("[data-bookmark-count]");
          if (countEl) countEl.textContent = String(payload.bookmarks || 0);
          bookmarkButton.dataset.defaultLabel = "Saved";
          bookmarkButton.textContent = "Saved";
          setPageFeedback("Post saved for later.", "stable");
        } catch (error) {
          setPageFeedback(error.message || "Post could not be saved.", "warning");
        } finally {
          setBusy(bookmarkButton, false, "Saving...");
        }
        return;
      }

      const reportButton = event.target.closest("[data-report-post]");
      if (reportButton) {
        const reason = window.prompt("Report reason (optional):", "Needs moderator review");
        if (reason === null) return;
        try {
          setBusy(reportButton, true, "Reporting...");
          await api("/api/community-report", {
            method: "POST",
            body: JSON.stringify({
              post_id: reportButton.dataset.postId,
              reason,
            }),
          });
          reportButton.dataset.defaultLabel = "Reported";
          reportButton.textContent = "Reported";
          reportButton.disabled = true;
          setPageFeedback("Report sent to moderation.", "stable");
        } catch (error) {
          setPageFeedback(error.message || "Report could not be submitted.", "warning");
        } finally {
          if (!reportButton.disabled) {
            setBusy(reportButton, false, "Reporting...");
          }
        }
        return;
      }

      const muteButton = event.target.closest("[data-mute-author]");
      if (muteButton) {
        const authorUsername = muteButton.dataset.authorUsername || "";
        if (!authorUsername) return;
        try {
          setBusy(muteButton, true, "Muting...");
          await api("/api/community-mute", {
            method: "POST",
            body: JSON.stringify({ author_username: authorUsername }),
          });
          document.querySelectorAll(`[data-post-author-username="${authorUsername}"]`).forEach((card) => {
            card.remove();
          });
          setPageFeedback("Author muted. Their posts were removed from this view.", "stable");
        } catch (error) {
          setPageFeedback(error.message || "Author could not be muted.", "warning");
        } finally {
          setBusy(muteButton, false, "Muting...");
        }
        return;
      }

      const replyButton = event.target.closest("[data-reply-post]");
      if (!replyButton) return;

      const postId = replyButton.dataset.postId;
      const card = replyButton.closest("[data-post-card]");
      const input = document.querySelector(`[data-reply-input="${postId}"]`);
      const content = input?.value.trim() || "";
      if (!content) {
        setPageFeedback("Write a reply before sending it.", "warning");
        return;
      }

      try {
        setBusy(replyButton, true, "Replying...");
        const payload = await api("/api/community-reply", {
          method: "POST",
          body: JSON.stringify({ post_id: postId, content }),
        });
        const replyList = card?.querySelector("[data-reply-list]");
        if (replyList) {
          replyList.appendChild(createReplyCard(payload.reply || {}));
        }
        const countEl = card?.querySelector("[data-reply-count]");
        if (countEl) {
          countEl.textContent = String(payload.reply_count || 0);
        }
        if (input) input.value = "";
        setPageFeedback("Reply sent.", "stable");
      } catch (error) {
        setPageFeedback(error.message || "Reply could not be sent.", "warning");
      } finally {
        setBusy(replyButton, false, "Replying...");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initMoviesPage();
    initTherapistsPage();
    initCommunityPage();
  });
})();
