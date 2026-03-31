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

  function initCommunityPage() {
    if (pageId !== "community") return;

    document.addEventListener("click", async (event) => {
      const postButton = event.target.closest("[data-submit-post]");
      if (postButton) {
        const groupId = document.querySelector("[data-community-group]")?.value || "grp-006";
        const content = document.querySelector("[data-community-post]")?.value.trim() || "";
        if (!content) {
          setPageFeedback("Write a few words before posting.", "warning");
          return;
        }

        try {
          setBusy(postButton, true, "Posting...");
          await api("/api/community-post", {
            method: "POST",
            body: JSON.stringify({ group_id: groupId, content }),
          });
          window.location.reload();
        } catch (error) {
          setPageFeedback(error.message || "Post could not be shared.", "warning");
        } finally {
          setBusy(postButton, false, "Posting...");
        }
        return;
      }

      const supportButton = event.target.closest("[data-support-post]");
      if (supportButton) {
        try {
          setBusy(supportButton, true, "Supporting...");
          await api("/api/community-react", {
            method: "POST",
            body: JSON.stringify({ post_id: supportButton.dataset.postId }),
          });
          window.location.reload();
        } catch (error) {
          setPageFeedback(error.message || "Support could not be sent.", "warning");
        } finally {
          setBusy(supportButton, false, "Supporting...");
        }
        return;
      }

      const replyButton = event.target.closest("[data-reply-post]");
      if (!replyButton) return;

      const postId = replyButton.dataset.postId;
      const input = document.querySelector(`[data-reply-input="${postId}"]`);
      const content = input?.value.trim() || "";
      if (!content) {
        setPageFeedback("Write a reply before sending it.", "warning");
        return;
      }

      try {
        setBusy(replyButton, true, "Replying...");
        await api("/api/community-reply", {
          method: "POST",
          body: JSON.stringify({ post_id: postId, content }),
        });
        window.location.reload();
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
