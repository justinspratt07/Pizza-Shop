document.addEventListener("DOMContentLoaded", () => {
  const emailInput = document.querySelector("#email");
  const emailStatus = document.querySelector("#email-status");

  if (emailInput && emailStatus) {
    let lastValue = "";
    emailInput.addEventListener("input", () => {
      const email = emailInput.value.trim();
      if (!email || email === lastValue) {
        emailStatus.textContent = "";
        return;
      }
      lastValue = email;

      fetch(`/api/check-email?email=${encodeURIComponent(email)}`)
        .then((response) => response.json())
        .then((data) => {
          if (data.exists) {
            emailStatus.textContent = "This email is already registered.";
            emailStatus.classList.add("error-text");
            emailStatus.classList.remove("success-text");
          } else {
            emailStatus.textContent = "This email is available.";
            emailStatus.classList.add("success-text");
            emailStatus.classList.remove("error-text");
          }
        })
        .catch(() => {
          emailStatus.textContent = "Unable to verify availability right now.";
          emailStatus.classList.add("error-text");
          emailStatus.classList.remove("success-text");
        });
    });
  }

  const zipInput = document.querySelector("#zip_code");
  const subtotalTotal = document.querySelector('[data-total="subtotal"]');
  const taxTotal = document.querySelector('[data-total="tax"]');
  const totalTotal = document.querySelector('[data-total="total"]');
  const taxLabel = document.querySelector('[data-total-label="tax"]');

  if (zipInput && subtotalTotal && taxTotal && totalTotal && taxLabel) {
    let lastZip = "";
    let debounceId;

    zipInput.addEventListener("input", () => {
      const zipCode = zipInput.value.replace(/\D/g, "").slice(0, 5);
      clearTimeout(debounceId);

      if (zipCode.length !== 5 || zipCode === lastZip) {
        return;
      }

      debounceId = setTimeout(() => {
        lastZip = zipCode;
        fetch(`/api/tax-estimate?zip_code=${encodeURIComponent(zipCode)}`)
          .then((response) => response.json())
          .then((data) => {
            if (data.error) {
              return;
            }
            subtotalTotal.textContent = data.subtotal;
            taxTotal.textContent = data.tax;
            totalTotal.textContent = data.total;
            taxLabel.textContent = `Tax (${data.tax_rate_display})`;
          })
          .catch(() => {});
      }, 250);
    });
  }
});
