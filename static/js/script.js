document.addEventListener("DOMContentLoaded", () => {

    /* ==========================================
       FLASH MESSAGE AUTO DISMISS
    ========================================== */

    document.querySelectorAll(".flash-message").forEach((message) => {
        let remainingTime = 5000;
        let startTime = 0;
        let timeoutId = null;

        const hideMessage = () => {
            message.classList.add("flash-hide");
            setTimeout(() => message.remove(), 400);
        };

        const startTimer = () => {
            if (timeoutId || message.classList.contains("flash-hide")) return;

            startTime = Date.now();

            timeoutId = setTimeout(() => {
                timeoutId = null;
                hideMessage();
            }, remainingTime);
        };

        const pauseTimer = () => {
            if (!timeoutId) return;

            clearTimeout(timeoutId);
            timeoutId = null;

            remainingTime = Math.max(
                0,
                remainingTime - (Date.now() - startTime)
            );
        };

        message.addEventListener("mouseenter", pauseTimer);

        message.addEventListener("mouseleave", () => {
            if (remainingTime <= 0) {
                hideMessage();
            } else {
                startTimer();
            }
        });

        startTimer();
    });


    /* ==========================================
       PAGE MODE
    ========================================== */

    const isAuthPage = document.body.classList.contains("auth-page-open");


    /* ==========================================
       MODAL ELEMENTS AND FUNCTIONS
    ========================================== */

    const getModal = (name) => {
        return document.querySelector(`[data-modal="${name}"]`);
    };

    let lastFocusedElement = null;

    const getFocusableElements = (container) => {
        if (!container) return [];

        return Array.from(
            container.querySelectorAll(
                'a[href], button:not([disabled]), input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )
        ).filter((element) => {
            return (
                element.getAttribute("aria-hidden") !== "true" &&
                !element.closest('[aria-hidden="true"]') &&
                !element.closest("[inert]") &&
                element.offsetParent !== null
            );
        });
    };

    const focusFirstElement = (container) => {
        const focusable = getFocusableElements(container);

        if (focusable.length > 0) {
            focusable[0].focus();
        } else if (container) {
            container.setAttribute("tabindex", "-1");
            container.focus();
        }
    };

    const openModal = (name) => {
        const modal = getModal(name);

        if (!modal) return;

        const visibleModals = document.querySelectorAll(
            "[data-modal].modal-visible"
        );

        if (visibleModals.length === 0) {
            lastFocusedElement = document.activeElement;
        }

        modal.removeAttribute("inert");
        modal.classList.add("modal-visible");
        modal.setAttribute("aria-hidden", "false");

        document.body.classList.add("modal-open");

        requestAnimationFrame(() => {
            if (name === "login") {
                const slider = modal.querySelector("[data-auth-slider]");
                const isRegister = slider?.classList.contains("show-register");

                const activePanel = modal.querySelector(
                    isRegister ? ".auth-register-panel" : ".auth-login-panel"
                );

                focusFirstElement(activePanel || modal);
            } else {
                focusFirstElement(modal);
            }
        });
    };

    const closeModal = (name) => {
        const modal = getModal(name);

        if (!modal) return;

        modal.classList.remove("modal-visible");
        modal.setAttribute("aria-hidden", "true");
        modal.setAttribute("inert", "");

        const visibleModals = document.querySelectorAll(
            "[data-modal].modal-visible"
        );

        if (visibleModals.length === 0) {
            document.body.classList.remove("modal-open");

            if (
                lastFocusedElement &&
                document.contains(lastFocusedElement)
            ) {
                lastFocusedElement.focus();
            }

            lastFocusedElement = null;
        }
    };


    /* ==========================================
       DOUBLE SLIDER INITIALIZATION
    ========================================== */

    const authSliders = document.querySelectorAll("[data-auth-slider]");

    const setAuthPanel = (slider, panel) => {
        if (!slider) return;

        const showRegister = panel === "register";

        const loginPanel = slider.querySelector(".auth-login-panel");
        const registerPanel = slider.querySelector(".auth-register-panel");

        slider.classList.toggle("show-register", showRegister);

        slider.dataset.activePanel = showRegister
            ? "register"
            : "login";

        slider.setAttribute(
            "aria-label",
            showRegister ? "Create Account" : "Welcome Back"
        );
        slider.setAttribute(
            "aria-labelledby",
            showRegister ? "auth-register-title" : "auth-dialog-title"
        );

        if (loginPanel) {
            loginPanel.setAttribute(
                "aria-hidden",
                showRegister ? "true" : "false"
            );

            if (showRegister) {
                loginPanel.setAttribute("inert", "");
            } else {
                loginPanel.removeAttribute("inert");
            }
        }

        if (registerPanel) {
            registerPanel.setAttribute(
                "aria-hidden",
                showRegister ? "false" : "true"
            );

            if (showRegister) {
                registerPanel.removeAttribute("inert");
            } else {
                registerPanel.setAttribute("inert", "");
            }
        }
    };


    /* ==========================================
       DIRECT LOGIN PAGE
       Keep the slider visible.
       Do not treat it as a closable modal.
    ========================================== */

    if (isAuthPage) {
        authSliders.forEach((slider) => {
            setAuthPanel(slider, slider.dataset.initialPanel || "login");
        });

        const loginModal = getModal("login");

        if (loginModal) {
            loginModal.classList.add("modal-visible");
            loginModal.removeAttribute("inert");
            loginModal.setAttribute("aria-hidden", "false");
        }

        document.body.classList.remove("modal-open");

    } else {
        /* Other pages: keep login modal hidden initially. */

        const loginModal = getModal("login");

        if (loginModal && !loginModal.classList.contains("modal-visible")) {
            loginModal.setAttribute("aria-hidden", "true");
            loginModal.setAttribute("inert", "");
        }
    }


    /* ==========================================
       OPEN LOGIN / REGISTER MODAL
       Used on other pages only.
    ========================================== */

    document.querySelectorAll("[data-open-modal]").forEach((button) => {
        button.addEventListener("click", () => {
            if (isAuthPage) return;

            const panel = button.dataset.openModal;

            if (panel !== "login" && panel !== "register") return;

            const modal = getModal("login");
            const slider = modal?.querySelector("[data-auth-slider]");

            if (!slider) return;

            setAuthPanel(slider, panel);
            openModal("login");
        });
    });


    /* ==========================================
       SWITCH LOGIN AND SIGN UP
    ========================================== */

    document.querySelectorAll("[data-switch-auth]").forEach((button) => {
        button.addEventListener("click", (event) => {
            event.preventDefault();

            const panel = button.dataset.switchAuth;

            if (panel !== "login" && panel !== "register") return;

            const slider = button.closest("[data-auth-slider]");

            if (!slider) return;

            setAuthPanel(slider, panel);

            const activePanel = slider.querySelector(
                panel === "register"
                    ? ".auth-register-panel"
                    : ".auth-login-panel"
            );

            requestAnimationFrame(() => {
                focusFirstElement(activePanel);
            });
        });
    });


    /* ==========================================
       CLOSE MODAL BUTTONS
    ========================================== */

    document.querySelectorAll("[data-close-modal]").forEach((button) => {
        button.addEventListener("click", () => {
            if (isAuthPage) return;

            const modal = button.closest("[data-modal]");

            if (modal) {
                closeModal(modal.dataset.modal);
            }
        });
    });


    /* ==========================================
       CLICK OUTSIDE TO CLOSE
    ========================================== */

    document.querySelectorAll("[data-modal]").forEach((modal) => {
        modal.addEventListener("click", (event) => {
            if (event.target !== modal || isAuthPage) return;

            closeModal(modal.dataset.modal);
        });
    });


    /* ==========================================
       KEYBOARD ACCESSIBILITY
    ========================================== */

    document.addEventListener("keydown", (event) => {
        const visibleModals = Array.from(
            document.querySelectorAll("[data-modal].modal-visible")
        );

        if (visibleModals.length === 0) return;

        const topModal = visibleModals[visibleModals.length - 1];

        if (event.key === "Escape") {
            if (
                isAuthPage &&
                topModal.dataset.modal === "login"
            ) {
                return;
            }

            event.preventDefault();
            closeModal(topModal.dataset.modal);
            return;
        }

        if (event.key === "Tab") {
            const focusable = getFocusableElements(topModal);

            if (focusable.length === 0) {
                event.preventDefault();
                topModal.focus();
                return;
            }

            const firstElement = focusable[0];
            const lastElement = focusable[focusable.length - 1];

            if (
                event.shiftKey &&
                (
                    document.activeElement === firstElement ||
                    !topModal.contains(document.activeElement)
                )
            ) {
                event.preventDefault();
                lastElement.focus();
            } else if (
                !event.shiftKey &&
                (
                    document.activeElement === lastElement ||
                    !topModal.contains(document.activeElement)
                )
            ) {
                event.preventDefault();
                firstElement.focus();
            }
        }
    });


    /* ==========================================
       REGISTRATION CONFIRMATION
    ========================================== */

    const registrationForms = document.querySelectorAll(
        "[data-registration-form]"
    );

    const cancelRegistration = document.querySelector(
        "[data-cancel-registration]"
    );

    const confirmRegistration = document.querySelector(
        "[data-confirm-registration]"
    );

    registrationForms.forEach((registrationForm) => {
        registrationForm.addEventListener("submit", (event) => {
            if (registrationForm.dataset.confirmed === "true") {
                registrationForm.dataset.confirmed = "false";
                return;
            }

            event.preventDefault();

            if (!registrationForm.reportValidity()) return;

            openModal("registration-confirm");
        });
    });


    /* ==========================================
       CANCEL REGISTRATION
    ========================================== */

    if (cancelRegistration) {
        cancelRegistration.addEventListener("click", () => {
            closeModal("registration-confirm");

            const registrationForm = document.querySelector(
                "[data-registration-form]"
            );

            const createAccountButton = registrationForm?.querySelector(
                'button[type="submit"], input[type="submit"]'
            );

            if (createAccountButton) {
                createAccountButton.focus();
            }
        });
    }


    /* ==========================================
       CONFIRM REGISTRATION
    ========================================== */

    if (confirmRegistration) {
        confirmRegistration.addEventListener("click", () => {
            const registrationForm = document.querySelector(
                "[data-registration-form]"
            );

            if (!registrationForm) {
                closeModal("registration-confirm");
                return;
            }

            if (!registrationForm.reportValidity()) {
                closeModal("registration-confirm");
                return;
            }

            registrationForm.dataset.confirmed = "true";

            closeModal("registration-confirm");

            if (typeof registrationForm.requestSubmit === "function") {
                registrationForm.requestSubmit();
            } else {
                registrationForm.submit();
            }
        });
    }


    /* ==========================================
       PASSWORD VISIBILITY
    ========================================== */

    document.querySelectorAll("[data-toggle-password]").forEach((button) => {
        button.addEventListener("click", (event) => {
            event.preventDefault();

            const wrapper = button.closest(".password-input-wrapper");

            if (!wrapper) return;

            const passwordInput = wrapper.querySelector("input");

            if (!passwordInput) return;

            const showPassword = passwordInput.type === "password";

            passwordInput.type = showPassword ? "text" : "password";

            button.setAttribute(
                "aria-label",
                showPassword ? "Hide password" : "Show password"
            );

            button.setAttribute(
                "aria-pressed",
                showPassword ? "true" : "false"
            );

            button.textContent = showPassword ? "Hide" : "Show";
        });
    });


    /* ==========================================
       DELETE CONFIRMATION
    ========================================== */

    document.querySelectorAll("[data-confirm-delete]").forEach((button) => {
        button.addEventListener("click", (event) => {
            const message = button.dataset.confirmDelete ||
                "Are you sure you want to delete this item?";

            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });


    /* ==========================================
       NUMBER INPUT VALIDATION
    ========================================== */

    document.querySelectorAll('input[type="number"]').forEach((input) => {
        input.addEventListener("change", () => {
            if (input.value === "") return;

            const value = Number(input.value);

            if (!Number.isFinite(value)) {
                input.value = "";
                return;
            }

            const min = input.min !== "" ? Number(input.min) : null;
            const max = input.max !== "" ? Number(input.max) : null;

            let correctedValue = value;

            if (min !== null && correctedValue < min) {
                correctedValue = min;
            }

            if (max !== null && correctedValue > max) {
                correctedValue = max;
            }

            input.value = correctedValue;
        });
    });


    /* ==========================================
       PREVENT DOUBLE FORM SUBMISSION
    ========================================== */

    document.querySelectorAll(
        "form[data-prevent-double-submit]"
    ).forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (event.defaultPrevented) return;

            if (form.dataset.submitting === "true") {
                event.preventDefault();
                return;
            }

            if (!form.reportValidity()) {
                event.preventDefault();
                return;
            }

            form.dataset.submitting = "true";

            const submitButtons = form.querySelectorAll(
                'button[type="submit"], input[type="submit"]'
            );

            submitButtons.forEach((button) => {
                button.disabled = true;

                if (button.tagName === "BUTTON") {
                    button.dataset.originalText = button.innerHTML;
                    button.innerHTML = "Please wait...";
                } else {
                    button.dataset.originalValue = button.value;
                    button.value = "Please wait...";
                }
            });
        });
    });


    /* ==========================================
       MOBILE NAVIGATION
    ========================================== */

    const menuToggle = document.querySelector("[data-menu-toggle]");
    const mainNav = document.querySelector("[data-navigation-menu]");

    if (menuToggle && mainNav) {
        const closeNavigation = () => {
            mainNav.classList.remove("nav-open");
            menuToggle.setAttribute("aria-expanded", "false");
        };

        const toggleNavigation = () => {
            const isOpen = mainNav.classList.toggle("nav-open");

            menuToggle.setAttribute(
                "aria-expanded",
                isOpen ? "true" : "false"
            );
        };

        menuToggle.addEventListener("click", (event) => {
            event.stopPropagation();
            toggleNavigation();
        });

        mainNav.addEventListener("click", (event) => {
            const clickedLink = event.target.closest("a, button");

            if (clickedLink) {
                closeNavigation();
            }
        });

        document.addEventListener("click", (event) => {
            if (
                mainNav.classList.contains("nav-open") &&
                !mainNav.contains(event.target) &&
                !menuToggle.contains(event.target)
            ) {
                closeNavigation();
            }
        });

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeNavigation();
            }
        });

        window.addEventListener("resize", () => {
            if (window.innerWidth > 600) {
                closeNavigation();
            }
        });
    }

});