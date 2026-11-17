(function () {
      'use strict';

      var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      var docEl = document.documentElement;

      /* ---------- API и данные сайта ---------- */
      var API_BASE = (window.SITE_API_BASE || (location.protocol === 'file:' ? 'http://127.0.0.1:8080' : '')).replace(/\/+$/, '');
      var siteData = null;
      var siteServices = [];
      var siteMasters = [];
      var statsGrid = document.getElementById('statsGrid');
      var statsSection = document.getElementById('statsSection');
      var statsSignature = '';
      var bookingEnabled = true;
      var bookingCompleted = false;
      var currentChannel = 'telegram';
      var slotRequest = 0;

      var STATIC_SERVICES = {
        'Стрижка': { id: 0, name: 'Стрижка', price: 4000, duration: 60 },
        'Борода': { id: 0, name: 'Борода', price: 2500, duration: 40 },
        'Комплекс': { id: 0, name: 'Комплекс', price: 6000, duration: 90 },
        'Детская стрижка': { id: 0, name: 'Детская стрижка', price: 3000, duration: 40 }
      };

      function escapeHtml(value) {
        return String(value == null ? '' : value)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
      }

      function onlyDigits(value) {
        return String(value == null ? '' : value).replace(/\D/g, '');
      }

      function formatMoney(value) {
        var number = Number(value);
        if (!isFinite(number)) number = 0;
        return number.toLocaleString('ru-RU').replace(/\u00A0/g, ' ');
      }

      function isoDay(offset) {
        var d = new Date();
        d.setHours(12, 0, 0, 0);
        d.setDate(d.getDate() + (offset || 0));
        var month = String(d.getMonth() + 1).padStart(2, '0');
        var day = String(d.getDate()).padStart(2, '0');
        return d.getFullYear() + '-' + month + '-' + day;
      }

      var MONTHS_RU = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
      var MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
      var WEEKDAYS_RU = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

      function buildDateOptions() {
        if (!dateInput) return;
        var html = '';
        for (var i = 0; i < 30; i++) {
          var d = new Date();
          d.setHours(12, 0, 0, 0);
          d.setDate(d.getDate() + i);
          var iso = isoDay(i);
          var label;
          if (i === 0) label = 'Сегодня';
          else if (i === 1) label = 'Завтра';
          else label = d.getDate() + ' ' + MONTHS_SHORT[d.getMonth()] + ', ' + WEEKDAYS_RU[d.getDay()];
          html += '<option value="' + iso + '">' + label + '</option>';
        }
        dateInput.innerHTML = html;
        dateInput.value = isoDay(0);
      }

      function formatDateHuman(iso) {
        if (!iso) return '';
        var parts = String(iso).split('-');
        if (parts.length !== 3) return iso;
        var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]), 12, 0, 0);
        return d.getDate() + ' ' + MONTHS_RU[d.getMonth()];
      }

      function fetchJson(url, options, timeout) {
        var controller = new AbortController();
        var timer = window.setTimeout(function () { controller.abort(); }, timeout || 6000);
        var opts = Object.assign({}, options || {}, { signal: controller.signal });
        return fetch(url, opts).then(function (response) {
          return response.json().catch(function () { return null; }).then(function (data) {
            return { response: response, data: data };
          });
        }).finally(function () {
          window.clearTimeout(timer);
        });
      }

      function findService(name) {
        if (!name) return null;
        for (var i = 0; i < siteServices.length; i++) {
          if (siteServices[i].name === name) return siteServices[i];
        }
        return STATIC_SERVICES[name] || null;
      }

      function findMaster(id) {
        if (!id) return null;
        for (var i = 0; i < siteMasters.length; i++) {
          if (String(siteMasters[i].id) === String(id)) return siteMasters[i];
        }
        return null;
      }

      function allServices() {
        if (siteServices.length) return siteServices;
        return Object.keys(STATIC_SERVICES).map(function (name) {
          return STATIC_SERVICES[name];
        });
      }

      function selectedServices() {
        return allServices().filter(function (service) {
          return selectedServiceNames.has(service.name);
        });
      }

      function renderServicePicker() {
        if (!servicePicker) return;
        var services = allServices();
        var available = {};
        services.forEach(function (service) { available[service.name] = true; });
        Array.from(selectedServiceNames).forEach(function (name) {
          if (!available[name]) selectedServiceNames.delete(name);
        });
        if (!services.length) {
          servicePicker.innerHTML = '<p class="services__empty">Список услуг обновляется. Позвоните нам.</p>';
          return;
        }
        servicePicker.innerHTML = services.map(function (service) {
          var checked = selectedServiceNames.has(service.name) ? ' checked' : '';
          return '<label class="service-choice">' +
            '<input type="checkbox" value="' + escapeHtml(service.name) + '" data-service-name="' + escapeHtml(service.name) + '"' + checked + '>' +
            '<span><strong>' + escapeHtml(service.name) + '</strong>' +
            '<small>' + formatMoney(service.price) + ' ₸ · ' + escapeHtml(service.duration) + ' мин</small></span>' +
            '</label>';
        }).join('');
      }

      function selectService(name, exclusive) {
        if (exclusive) selectedServiceNames.clear();
        if (name) selectedServiceNames.add(name);
        renderServicePicker();
        updateServiceHint();
      }

      function initialsFromName(name) {
        var parts = String(name || '').trim().split(/\s+/).filter(Boolean);
        if (!parts.length) return 'Б';
        if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
        return (parts[0][0] + parts[1][0]).toUpperCase();
      }

      /* ---------- Шапка при скролле ---------- */
      var header = document.getElementById('header');
      var ticking = false;

      function updateHeader() {
        if (window.scrollY > 24) {
          header.classList.add('is-scrolled');
        } else {
          header.classList.remove('is-scrolled');
        }
        ticking = false;
      }

      window.addEventListener('scroll', function () {
        if (!ticking) {
          window.requestAnimationFrame(updateHeader);
          ticking = true;
        }
      }, { passive: true });
      updateHeader();

      /* ---------- Блокировка прокрутки ---------- */
      var locks = new Set();

      function syncLock() {
        docEl.classList.toggle('is-locked', locks.size > 0);
      }

      function lockScroll(key) {
        locks.add(key);
        syncLock();
      }

      function unlockScroll(key) {
        locks.delete(key);
        syncLock();
      }

      /* ---------- Появление блоков ---------- */
      var revealEls = Array.prototype.slice.call(document.querySelectorAll('.reveal'));

      if (reduceMotion || !('IntersectionObserver' in window)) {
        revealEls.forEach(function (el) { el.classList.add('is-in'); });
      } else {
        var revealObserver = new IntersectionObserver(function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              entry.target.classList.add('is-in');
              revealObserver.unobserve(entry.target);
            }
          });
        }, { threshold: 0.08, rootMargin: '0px 0px -4% 0px' });

        revealEls.forEach(function (el) { revealObserver.observe(el); });
      }

      /* ---------- Анимация цифр ---------- */
      function formatNumber(value, decimals) {
        if (decimals > 0) return value.toFixed(decimals);
        return Math.round(value).toLocaleString('ru-RU');
      }

      function initCounters(scope) {
        var root = scope || document;
        var counters = Array.prototype.slice.call(root.querySelectorAll('[data-count]'));

        counters.forEach(function (el) {
          if (el.getAttribute('data-counter-ready') === '1') return;
          el.setAttribute('data-counter-ready', '1');
          var target = parseFloat(el.getAttribute('data-count'));
          var decimals = parseInt(el.getAttribute('data-decimals') || '0', 10);
          if (!isFinite(target)) return;

          if (reduceMotion || !('IntersectionObserver' in window)) {
            el.textContent = formatNumber(target, decimals);
            return;
          }

          el.textContent = formatNumber(0, decimals);

          var counterObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
              if (!entry.isIntersecting) return;

              target = parseFloat(el.getAttribute('data-count'));
              var duration = 1400;
              var start = performance.now();

              function frame(now) {
                var progress = Math.min((now - start) / duration, 1);
                var eased = 1 - Math.pow(1 - progress, 4);
                el.textContent = formatNumber(target * eased, decimals);

                if (progress < 1) {
                  window.requestAnimationFrame(frame);
                } else {
                  el.textContent = formatNumber(target, decimals);
                }
              }

              window.requestAnimationFrame(frame);
              counterObserver.disconnect();
            });
          }, { threshold: 0.6 });

          counterObserver.observe(el);
        });
      }

      initCounters(document);

      /* ---------- Мобильное меню ---------- */
      var burger = document.getElementById('burger');
      var mobileMenu = document.getElementById('mobileMenu');
      var pageMain = document.getElementById('main');
      var pageFooter = document.querySelector('.footer');
      var menuOpen = false;
      var menuTimer = null;

      function setMenu(open) {
        if (open === menuOpen) return;
        menuOpen = open;
        window.clearTimeout(menuTimer);

        if (open) {
          mobileMenu.hidden = false;
          window.requestAnimationFrame(function () {
            mobileMenu.classList.add('is-open');
          });
          burger.setAttribute('aria-expanded', 'true');
          burger.setAttribute('aria-label', 'Закрыть меню');
          if (pageMain) pageMain.setAttribute('inert', '');
          if (pageFooter) pageFooter.setAttribute('inert', '');
          lockScroll('menu');
        } else {
          mobileMenu.classList.remove('is-open');
          burger.setAttribute('aria-expanded', 'false');
          burger.setAttribute('aria-label', 'Открыть меню');
          if (pageMain) pageMain.removeAttribute('inert');
          if (pageFooter) pageFooter.removeAttribute('inert');
          unlockScroll('menu');

          menuTimer = window.setTimeout(function () {
            if (!menuOpen) mobileMenu.hidden = true;
          }, 380);
        }
      }

      burger.addEventListener('click', function () {
        setMenu(!menuOpen);
      });

      mobileMenu.querySelectorAll('a').forEach(function (link) {
        link.addEventListener('click', function () {
          setMenu(false);
        });
      });

      /* ---------- Модальное окно ---------- */
      var modal = document.getElementById('bookingModal');
      var form = document.getElementById('bookingForm');
      var nameInput = document.getElementById('name');
      var phoneInput = document.getElementById('phone');
      var servicePicker = document.getElementById('servicePicker');
      var serviceError = document.getElementById('serviceError');
      var selectedServiceNames = new Set();
      var masterSelect = document.getElementById('master');
      var masterHint = document.getElementById('masterHint');
      var consentInput = document.getElementById('consent');
      var consentHint = document.getElementById('consentHint');
      var dateInput = document.getElementById('date');
      var timeSelect = document.getElementById('time');
      var commentInput = document.getElementById('comment');
      var companyInput = document.getElementById('company');
      var channelInput = document.getElementById('channel');
      var channelBtns = Array.prototype.slice.call(document.querySelectorAll('.channel__btn'));
      var serviceHint = document.getElementById('serviceHint');
      var bookingError = document.getElementById('bookingError');
      var bookingErrorText = document.getElementById('bookingErrorText');
      var fallbackWa = document.getElementById('fallbackWa');
      var bookingIntro = document.getElementById('bookingIntro');
      var bookingSuccess = document.getElementById('bookingSuccess');
      var successLead = document.getElementById('successLead');
      var successSummary = document.getElementById('successSummary');
      var successWhatsapp = document.getElementById('successWhatsapp');
      var submitBtn = form.querySelector('.modal__submit');
      var submitLabel = submitBtn.textContent;
      var modalOpen = false;
      var closeTimer = null;
      var lastFocused = null;

      /* ---------- Просмотр фото ---------- */
      var lightbox = document.getElementById('galleryLightbox');
      var lightboxImage = document.getElementById('lightboxImage');
      var lightboxCaption = document.getElementById('lightboxCaption');
      var lightboxCount = document.getElementById('lightboxCount');
      var lightboxItems = [];
      var lightboxIndex = 0;
      var lightboxOpener = null;

      function galleryItems() {
        var grid = document.querySelector('.gallery__grid');
        if (!grid) return [];
        return Array.prototype.slice.call(grid.querySelectorAll('.shot[data-full-src]'));
      }

      function renderLightbox() {
        if (!lightbox || !lightboxImage) return;
        var figure = lightboxItems[lightboxIndex];
        if (!figure) return;
        var image = figure.querySelector('.shot__img');
        var caption = figure.getAttribute('data-caption') || '';
        lightboxImage.src = (image && image.getAttribute('src')) || figure.getAttribute('data-full-src') || '';
        lightboxImage.alt = (image && image.alt) || caption || 'Фото барбершопа';
        if (lightboxCaption) lightboxCaption.textContent = caption;
        if (lightboxCount) {
          lightboxCount.textContent = lightboxItems.length > 1
            ? (lightboxIndex + 1) + ' / ' + lightboxItems.length
            : '';
        }
        var prev = lightbox.querySelector('[data-lightbox-prev]');
        var next = lightbox.querySelector('[data-lightbox-next]');
        if (prev) prev.disabled = lightboxItems.length < 2;
        if (next) next.disabled = lightboxItems.length < 2;
      }

      function openLightbox(figure) {
        if (!lightbox || !figure) return;
        lightboxItems = galleryItems();
        lightboxIndex = lightboxItems.indexOf(figure);
        if (lightboxIndex < 0) return;
        lightboxOpener = figure;
        renderLightbox();
        lightbox.hidden = false;
        document.body.classList.add('is-lightbox');
        var close = lightbox.querySelector('.lightbox__close');
        if (close) close.focus();
      }

      function closeLightbox() {
        if (!lightbox || lightbox.hidden) return;
        lightbox.hidden = true;
        document.body.classList.remove('is-lightbox');
        if (lightboxImage) {
          lightboxImage.removeAttribute('src');
          lightboxImage.alt = '';
        }
        if (lightboxOpener && document.contains(lightboxOpener)) {
          lightboxOpener.focus();
        }
        lightboxOpener = null;
      }

      function stepLightbox(delta) {
        if (!lightbox || lightbox.hidden || lightboxItems.length < 2) return;
        lightboxIndex = (lightboxIndex + delta + lightboxItems.length) % lightboxItems.length;
        renderLightbox();
      }

      if (lightbox) {
        lightbox.addEventListener('click', function (event) {
          var target = event.target;
          if (!(target instanceof Element)) return;
          if (target.closest('[data-lightbox-close]')) {
            closeLightbox();
            return;
          }
          if (target.closest('[data-lightbox-prev]')) {
            stepLightbox(-1);
            return;
          }
          if (target.closest('[data-lightbox-next]')) {
            stepLightbox(1);
          }
        });

        document.addEventListener('keydown', function (event) {
          if (lightbox.hidden) return;
          if (event.key === 'Escape') {
            event.preventDefault();
            closeLightbox();
            return;
          }
          if (event.key === 'ArrowLeft') {
            event.preventDefault();
            stepLightbox(-1);
            return;
          }
          if (event.key === 'ArrowRight') {
            event.preventDefault();
            stepLightbox(1);
            return;
          }
          if (event.key === 'Tab') {
            var focusable = Array.prototype.slice.call(
              lightbox.querySelectorAll('button:not([disabled])')
            ).filter(function (el) { return el.offsetParent !== null; });
            if (!focusable.length) return;
            var first = focusable[0];
            var last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first.focus();
            }
          }
        });
      }

      var galleryGrid = document.querySelector('.gallery__grid');
      if (galleryGrid) {
        galleryGrid.addEventListener('click', function (event) {
          var target = event.target;
          if (!(target instanceof Element)) return;
          var figure = target.closest('.shot[data-full-src]');
          if (figure) openLightbox(figure);
        });
        galleryGrid.addEventListener('keydown', function (event) {
          if (event.key !== 'Enter' && event.key !== ' ') return;
          var target = event.target;
          if (!(target instanceof Element)) return;
          var figure = target.closest('.shot[data-full-src]');
          if (!figure || target !== figure) return;
          event.preventDefault();
          openLightbox(figure);
        });
      }

      function resetSubmit() {
        submitBtn.textContent = submitLabel;
        submitBtn.disabled = false;
      }

      function syncBookingState() {
        if (!bookingEnabled) {
          submitBtn.disabled = true;
          submitBtn.textContent = 'Онлайн-запись закрыта';
          return;
        }
        if (!consentInput || !consentInput.checked) {
          submitBtn.disabled = true;
          submitBtn.textContent = 'Отметьте согласие';
          return;
        }
        resetSubmit();
      }

      function setChannel(channel) {
        currentChannel = channel === 'whatsapp' ? 'whatsapp' : 'telegram';
        if (channelInput) channelInput.value = currentChannel;
        channelBtns.forEach(function (btn) {
          btn.setAttribute('aria-pressed', btn.getAttribute('data-channel') === currentChannel ? 'true' : 'false');
        });
      }

      function updateServiceHint() {
        if (!serviceHint) return;
        var services = selectedServices();
        if (!services.length) {
          serviceHint.textContent = 'Выберите одну или несколько услуг — покажем общую цену и длительность.';
          return;
        }
        var duration = services.reduce(function (sum, item) { return sum + (Number(item.duration) || 0); }, 0);
        var price = services.reduce(function (sum, item) { return sum + (Number(item.price) || 0); }, 0);
        serviceHint.innerHTML = services.length + ' ' + (services.length === 1 ? 'услуга' : 'услуги') +
          ' · ' + duration + ' мин · <b>' + formatMoney(price) + ' ₸</b>';
      }

      function updateMasterHint() {
        if (!masterHint) return;
        var master = findMaster(masterSelect ? masterSelect.value : '');
        if (master) {
          var description = String(master.description || '').trim();
          if (description.length > 140) description = description.slice(0, 137) + '…';
          masterHint.textContent = (description ? description + ' · ' : '') + (master.hours || 'График мастера указан при записи.');
        } else {
          masterHint.textContent = 'Можно выбрать конкретного мастера или любого свободного.';
        }
      }

      function parseMinutes(value) {
        var parts = String(value || '').split(':');
        return (Number(parts[0]) || 0) * 60 + (Number(parts[1]) || 0);
      }

      function localSlots(day, duration) {
        var settings = siteData && siteData.settings ? siteData.settings : {};
        var step = parseInt(settings.slot_step || '30', 10) || 30;
        var start = parseMinutes(settings.work_start || '10:00');
        var last = parseMinutes(settings.last_slot || '20:00');
        var end = parseMinutes(settings.work_end || '21:00');
        var selectedMaster = findMaster(masterSelect ? masterSelect.value : '');
        var lunchStart = selectedMaster && selectedMaster.break_start ? parseMinutes(selectedMaster.break_start) : -1;
        var lunchEnd = selectedMaster && selectedMaster.break_end ? parseMinutes(selectedMaster.break_end) : -1;
        var hasLunch = lunchStart >= 0 && lunchEnd > lunchStart;
        if (!day || day < isoDay(0) || day > isoDay(60)) return [];
        var now = new Date();
        var nowMinutes = now.getHours() * 60 + now.getMinutes();
        var slots = [];
        for (var t = start; t <= last; t += step) {
          if (day === isoDay(0) && t <= nowMinutes + 15) continue;
          if (hasLunch && t < lunchEnd && t + duration > lunchStart) continue;
          if (t + duration <= end) {
            slots.push(String(Math.floor(t / 60)).padStart(2, '0') + ':' + String(t % 60).padStart(2, '0'));
          }
        }
        return slots;
      }

      function updateTimeHint(day, slots) {
        var hint = document.getElementById('timeHint');
        if (!hint) return;
        var settings = siteData && siteData.settings ? siteData.settings : {};
        var start = settings.work_start || '10:00';
        if (day === isoDay(0)) {
          if (!slots || !slots.length) {
            hint.textContent = 'На сегодня свободного времени уже нет. Выберите другую дату.';
            hint.hidden = false;
            return;
          }
          if (slots[0] > start) {
            hint.textContent = 'Сегодня доступно с ' + slots[0] + ' — более раннее время уже прошло или занято. Выберите другую дату, чтобы увидеть полный день.';
            hint.hidden = false;
            return;
          }
        }
        hint.textContent = '';
        hint.hidden = true;
      }

      function fillTimeSlots(slots) {
        var previous = timeSelect.value;
        timeSelect.innerHTML = '';
        if (!slots || !slots.length) {
          var empty = document.createElement('option');
          empty.value = '';
          empty.textContent = 'Нет мест';
          timeSelect.appendChild(empty);
          return;
        }
        var placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Выберите';
        timeSelect.appendChild(placeholder);
        slots.forEach(function (slot) {
          var option = document.createElement('option');
          option.value = slot;
          option.textContent = slot;
          timeSelect.appendChild(option);
        });
        if (previous && slots.indexOf(previous) !== -1) timeSelect.value = previous;
      }

      function loadSlots(silent) {
        var day = dateInput.value;
        var services = selectedServices();
        var duration = services.reduce(function (sum, item) { return sum + (Number(item.duration) || 0); }, 0) || 30;
        var serviceIds = services.filter(function (item) { return item.id; }).map(function (item) { return item.id; });
        if (!day) return;
        var requestId = ++slotRequest;
        if (!silent) timeSelect.innerHTML = '<option value="">Загрузка…</option>';
        var localFallback = function () {
          if (requestId !== slotRequest) return;
          var fallback = localSlots(day, duration);
          fillTimeSlots(fallback);
          updateTimeHint(day, fallback);
        };
        var masterId = masterSelect && masterSelect.value ? masterSelect.value : '';
        var url = API_BASE + '/api/slots?date=' + encodeURIComponent(day) +
          (serviceIds.length ? '&service_ids=' + encodeURIComponent(serviceIds.join(',')) : '') +
          (masterId ? '&master_id=' + encodeURIComponent(masterId) : '');
        fetchJson(url, null, 2500).then(function (result) {
          if (requestId !== slotRequest) return;
          if (result.response && result.response.ok && result.data && Array.isArray(result.data.slots)) {
            fillTimeSlots(result.data.slots);
            updateTimeHint(day, result.data.slots);
          } else {
            localFallback();
          }
        }).catch(localFallback);
      }

      function clearBookingError() {
        if (!bookingError) return;
        bookingError.hidden = true;
        fallbackWa.hidden = true;
        fallbackWa.removeAttribute('href');
        bookingErrorText.textContent = '';
        syncBookingState();
      }

      function showBookingError(message, fallbackUrl) {
        bookingErrorText.textContent = message;
        if (fallbackUrl) {
          fallbackWa.href = fallbackUrl;
          fallbackWa.hidden = false;
        } else {
          fallbackWa.hidden = true;
          fallbackWa.removeAttribute('href');
        }
        bookingError.hidden = false;
        syncBookingState();
        if (modalOpen) {
          bookingError.scrollIntoView({ block: 'nearest', behavior: reduceMotion ? 'auto' : 'smooth' });
        }
      }

      function showSuccess(data) {
        bookingCompleted = true;
        if (data.access_token) rememberBookingToken(data.access_token);
        form.hidden = true;
        bookingIntro.hidden = true;
        bookingSuccess.hidden = false;
        modal.setAttribute('aria-labelledby', 'bookingSuccessTitle');
        var channelName = data.channel === 'whatsapp' ? 'WhatsApp' : 'Telegram';
        successLead.textContent = 'Мастер свяжется с вами в ' + channelName + ', чтобы подтвердить время.';
        successSummary.innerHTML =
          '<b>' + escapeHtml(data.service || selectedServices().map(function (item) { return item.name; }).join(' + ')) + '</b><br> ' +
          (data.master ? 'Мастер: ' + escapeHtml(data.master) + '<br> ' : '') +
          escapeHtml(formatDateHuman(data.date)) + ', ' + escapeHtml(data.time) + '<br> ' +
          escapeHtml(formatMoney(data.price)) + ' ₸' +
          (data.order_id ? '<br> Заявка №' + escapeHtml(data.order_id) : '');
        var wa = siteData && siteData.contacts && siteData.contacts.whatsapp ? siteData.contacts.whatsapp : '77000000000';
        if (data.channel === 'whatsapp' && wa) {
          var message = 'Здравствуйте! Я оставил заявку №' + (data.order_id || '') + ' на ' +
            formatDateHuman(data.date) + ' в ' + data.time + ', ' + (data.service || '') +
            (data.master ? ', мастер ' + data.master : '') + '.';
          successWhatsapp.href = 'https://wa.me/' + String(wa).replace(/\D/g, '') + '?text=' + encodeURIComponent(message);
          successWhatsapp.hidden = false;
        } else {
          successWhatsapp.hidden = true;
          successWhatsapp.removeAttribute('href');
        }
        bookingSuccess.focus({ preventScroll: true });
      }

      function resetBookingUI() {
        bookingCompleted = false;
        form.hidden = false;
        bookingIntro.hidden = false;
        bookingSuccess.hidden = true;
        modal.setAttribute('aria-labelledby', 'bookingTitle');
        bookingError.hidden = true;
        fallbackWa.hidden = true;
        form.reset();
        setChannel('telegram');
        selectedServiceNames.clear();
        renderServicePicker();
        if (masterSelect) masterSelect.value = '';
        if (consentInput) consentInput.checked = false;
        if (consentHint) consentHint.hidden = false;
        if (dateInput) dateInput.value = isoDay(0);
        timeSelect.innerHTML = '<option value="">Выберите</option>';
        var timeHint = document.getElementById('timeHint');
        if (timeHint) { timeHint.textContent = ''; timeHint.hidden = true; }
        updateServiceHint();
        updateMasterHint();
        syncBookingState();
      }

      function openModal(service, source) {
        if (menuOpen) {
          lastFocused = burger;
          setMenu(false);
        } else if (source && source.closest('.mobile-menu')) {
          lastFocused = burger;
        } else if (source) {
          lastFocused = source;
        } else if (document.activeElement && document.activeElement !== document.body) {
          lastFocused = document.activeElement;
        }

        if (bookingCompleted) resetBookingUI();
        syncBookingState();

        if (!modalOpen) {
          modal.hidden = false;
          window.requestAnimationFrame(function () {
            modal.classList.add('is-open');
          });
          lockScroll('modal');
          modalOpen = true;
        }

        window.clearTimeout(closeTimer);

        if (service) {
          selectService(service, true);
        }

        var presetMasterId = source ? (source.getAttribute('data-master-id') || '') : '';
        var presetMasterName = source ? (source.getAttribute('data-master') || '') : '';
        if (masterSelect && presetMasterId) {
          var masterExists = Array.prototype.some.call(masterSelect.options, function (option) {
            return option.value === String(presetMasterId);
          });
          if (!masterExists) {
            var masterOption = document.createElement('option');
            masterOption.value = String(presetMasterId);
            masterOption.textContent = presetMasterName || 'Мастер';
            masterSelect.appendChild(masterOption);
          }
          masterSelect.value = String(presetMasterId);
        } else if (masterSelect && !presetMasterId) {
          masterSelect.value = '';
        }

        if (dateInput && (!dateInput.value || dateInput.value < isoDay(0))) {
          dateInput.value = isoDay(0);
        }
        if (dateInput && dateInput.value === isoDay(0)) {
          var lastSlot = (siteData && siteData.settings && siteData.settings.last_slot) || '20:00';
          var nowDate = new Date();
          if (nowDate.getHours() * 60 + nowDate.getMinutes() >= parseMinutes(lastSlot)) {
            dateInput.value = isoDay(1);
          }
        }
        updateServiceHint();
        updateMasterHint();
        loadSlots();

        if (!bookingEnabled) {
          showBookingError('Онлайн-запись временно недоступна. Позвоните нам — подберём время вручную.');
        } else {
          clearBookingError();
        }

        window.setTimeout(function () {
          if (!modalOpen) return;
          var isTouch = (navigator.maxTouchPoints || 0) > 0 ||
            window.matchMedia('(pointer:coarse)').matches ||
            window.matchMedia('(hover:none)').matches;
          if (!isTouch) {
            nameInput.focus();
          } else {
            var closeBtn = modal.querySelector('.modal__close');
            if (closeBtn) closeBtn.focus({ preventScroll: true });
          }
        }, 320);
      }

      function closeModal() {
        if (!modalOpen) return;

        resetSubmit();
        modal.classList.remove('is-open');
        unlockScroll('modal');
        modalOpen = false;

        closeTimer = window.setTimeout(function () {
          modal.hidden = true;
          if (lastFocused && lastFocused.getClientRects().length) {
            lastFocused.focus();
          }
          lastFocused = null;
          if (bookingCompleted) resetBookingUI();
        }, 380);
      }

      document.addEventListener('click', function (event) {
        var trigger = event.target.closest ? event.target.closest('[data-booking]') : null;
        if (!trigger) return;
        event.preventDefault();
        openModal(trigger.getAttribute('data-service'), trigger);
      });

      channelBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
          setChannel(btn.getAttribute('data-channel'));
        });
      });

      if (servicePicker) {
        servicePicker.addEventListener('change', function (event) {
          var input = event.target;
          if (!input || input.type !== 'checkbox') return;
          if (input.checked) selectedServiceNames.add(input.value);
          else selectedServiceNames.delete(input.value);
          if (serviceError) { serviceError.hidden = true; serviceError.textContent = ''; }
          updateServiceHint();
          clearBookingError();
          loadSlots();
        });
      }

      if (masterSelect) {
        masterSelect.addEventListener('change', function () {
          updateMasterHint();
          clearBookingError();
          loadSlots();
        });
      }

      if (consentInput) {
        consentInput.addEventListener('change', function () {
          if (consentInput.checked && consentHint) consentHint.hidden = true;
          else if (consentHint) consentHint.hidden = false;
          syncBookingState();
        });
      }

      if (dateInput) {
        dateInput.addEventListener('change', function () {
          clearBookingError();
          loadSlots();
        });
      }

      if (timeSelect) {
        timeSelect.addEventListener('change', function () {
          if (timeSelect.value) clearBookingError();
        });
      }

      setChannel('telegram');
      updateServiceHint();

      modal.querySelectorAll('[data-close]').forEach(function (el) {
        el.addEventListener('click', closeModal);
      });

      modal.addEventListener('keydown', function (event) {
        if (event.key !== 'Tab') return;

        var focusable = Array.prototype.filter.call(
          modal.querySelectorAll('a[href],button:not([disabled]),input:not([type="hidden"]),select,textarea'),
          function (el) { return el.getClientRects().length > 0; }
        );
        if (!focusable.length) return;

        var first = focusable[0];
        var last = focusable[focusable.length - 1];

        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      });

      document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        if (myBookingsOpen) closeMyBookings();
        else if (modalOpen) closeModal();
        else if (menuOpen) setMenu(false);
      });

      /* ---------- Валидация и отправка заявки ---------- */
      function setError(input, message) {
        input.classList.add('is-error');
        input.setAttribute('aria-invalid', 'true');
        var error = input.closest('.field').querySelector('.field__error');
        if (error) {
          error.textContent = message;
          error.hidden = false;
        }
      }

      function clearError(input) {
        input.classList.remove('is-error');
        input.removeAttribute('aria-invalid');
        var error = input.closest('.field').querySelector('.field__error');
        if (error) {
          error.textContent = '';
          error.hidden = true;
        }
      }

      [nameInput, phoneInput].forEach(function (input) {
        input.addEventListener('input', function () { clearError(input); });
      });

      function offerWhatsAppFallback(name, phone, date, time, comment) {
        var waNumber = siteData && siteData.contacts && siteData.contacts.whatsapp
          ? siteData.contacts.whatsapp
          : '77000000000';
        var master = findMaster(masterSelect ? masterSelect.value : '');
        var selected = selectedServices();
        var text = 'Здравствуйте! Хочу записаться.\n' +
          'Имя: ' + name + '\n' +
          'Телефон: ' + phone + '\n' +
          'Услуги: ' + (selected.length ? selected.map(function (item) { return item.name; }).join(', ') : 'не выбраны') + '\n' +
          'Мастер: ' + (master ? master.name : 'любой свободный') + '\n' +
          'Дата: ' + formatDateHuman(date) + '\n' +
          'Время: ' + time + '\n' +
          'Связь: ' + (currentChannel === 'whatsapp' ? 'WhatsApp' : 'Telegram');
        if (comment) text += '\nКомментарий: ' + comment;
        var waUrl = 'https://wa.me/' + String(waNumber).replace(/\D/g, '') + '?text=' + encodeURIComponent(text);
        showBookingError(
          'Сервер записи недоступен. Отправьте заявку напрямую в WhatsApp — кнопка ниже.',
          waUrl
        );
      }

      form.addEventListener('submit', function (event) {
        event.preventDefault();
        if (submitBtn.disabled) return;

        clearBookingError();
        var name = nameInput.value.trim();
        var phone = phoneInput.value.trim();
        var digits = phone.replace(/\D/g, '');
        var selected = selectedServices();
        var valid = true;
        var focusEl = null;

        if (name.length < 2) {
          setError(nameInput, 'Укажите имя — хотя бы два символа');
          valid = false;
          focusEl = nameInput;
        }

        if (digits.length < 10) {
          setError(phoneInput, 'Укажите телефон в формате +7 700 000 00 00');
          valid = false;
          if (!focusEl) focusEl = phoneInput;
        }

        if (!selected.length) {
          if (serviceError) {
            serviceError.textContent = 'Выберите хотя бы одну услугу';
            serviceError.hidden = false;
          }
          valid = false;
          if (!focusEl) focusEl = servicePicker;
        }

        if (!dateInput.value || dateInput.value < isoDay(0)) {
          showBookingError('Выберите корректную дату.');
          valid = false;
          if (!focusEl) focusEl = dateInput;
        }

        if (!timeSelect.value) {
          showBookingError('Выберите время.');
          valid = false;
          if (!focusEl) focusEl = timeSelect;
        }

        if (!valid) {
          if (focusEl) focusEl.focus();
          return;
        }

        if (!bookingEnabled) {
          showBookingError('Онлайн-запись временно недоступна. Позвоните нам — подберём время вручную.');
          return;
        }

        if (!consentInput || !consentInput.checked) {
          showBookingError('Подтвердите согласие с политикой обработки персональных данных.');
          if (consentHint) consentHint.hidden = false;
          if (consentInput) consentInput.focus();
          return;
        }

        var payload = {
          name: name,
          phone: phone,
          service_ids: selected.filter(function (item) { return item.id; }).map(function (item) { return item.id; }),
          services: selected.map(function (item) { return item.name; }),
          service: selected.map(function (item) { return item.name; }).join(' + '),
          master_id: masterSelect && masterSelect.value ? Number(masterSelect.value) : null,
          consent: true,
          date: dateInput.value,
          time: timeSelect.value,
          channel: currentChannel,
          comment: commentInput.value.trim(),
          company: companyInput ? companyInput.value : ''
        };

        submitBtn.textContent = 'Отправляем…';
        submitBtn.disabled = true;

        fetchJson(API_BASE + '/api/bookings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        }, 7000).then(function (result) {
          if (result.data && result.data.ok) {
            showSuccess(result.data);
            return;
          }
          if (result.data && result.data.error) {
            showBookingError(result.data.error);
            if (result.response && result.response.status === 409) {
              loadSlots();
              timeSelect.focus();
            }
            return;
          }
          offerWhatsAppFallback(name, phone, dateInput.value, timeSelect.value, commentInput.value.trim());
        }).catch(function () {
          offerWhatsAppFallback(name, phone, dateInput.value, timeSelect.value, commentInput.value.trim());
        });
      });

      /* ---------- Мои записи на сайте ---------- */
      var MY_TOKENS_KEY = 'lezvie_site_booking_tokens';
      var myBookingsModal = document.getElementById('myBookingsModal');
      var myBookingsList = document.getElementById('myBookingsList');
      var myBookingsMessage = document.getElementById('myBookingsMessage');
      var myBookingsError = document.getElementById('myBookingsError');
      var myBookingsErrorText = document.getElementById('myBookingsErrorText');
      var myBookingsOpen = false;
      var myOrders = [];
      var myCancelId = 0;
      var myRescheduleId = 0;
      var myRescheduleDate = '';
      var myRescheduleSlots = [];
      var myRescheduleLoading = false;
      var myNotice = '';
      var myBookingsLastFocus = null;
      var myBookingsAlert = document.getElementById('myBookingsAlert');

      function readMyTokens() {
        try {
          var raw = window.localStorage.getItem(MY_TOKENS_KEY);
          var parsed = raw ? JSON.parse(raw) : [];
          return Array.isArray(parsed) ? parsed.filter(function (token) { return typeof token === 'string' && token; }).slice(0, 20) : [];
        } catch (error) {
          return [];
        }
      }

      function rememberBookingToken(token) {
        if (!token) return;
        try {
          var tokens = readMyTokens();
          if (tokens.indexOf(token) === -1) tokens.unshift(token);
          window.localStorage.setItem(MY_TOKENS_KEY, JSON.stringify(tokens.slice(0, 20)));
        } catch (error) {
          /* Приватный режим — кабинет просто не сохранится. */
        }
      }

      function myDateLabel(iso) {
        if (!iso) return '';
        var parts = String(iso).split('-');
        if (parts.length !== 3) return iso;
        var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]), 12, 0, 0);
        return d.getDate() + ' ' + MONTHS_SHORT[d.getMonth()] + ', ' + WEEKDAYS_RU[d.getDay()];
      }

      function myDateOptions(selected) {
        var html = '';
        for (var i = 0; i < 14; i++) {
          var iso = isoDay(i);
          var label = i === 0 ? 'Сегодня' : (i === 1 ? 'Завтра' : myDateLabel(iso));
          html += '<option value="' + iso + '"' + (iso === selected ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
        }
        return html;
      }

      function showMyError(message) {
        if (!myBookingsError || !myBookingsErrorText) return;
        myBookingsErrorText.textContent = message;
        myBookingsError.hidden = false;
      }

      function clearMyError() {
        if (!myBookingsError) return;
        myBookingsError.hidden = true;
        if (myBookingsErrorText) myBookingsErrorText.textContent = '';
      }

      function renderMyBookings() {
        if (!myBookingsList || !myBookingsMessage) return;
        if (!myOrders.length) {
          myBookingsList.innerHTML = '';
          myBookingsMessage.hidden = false;
          myBookingsMessage.textContent = readMyTokens().length
            ? 'Активных записей нет. Самое время записаться.'
            : 'На этом устройстве записей нет. Запишитесь через сайт — и они появятся здесь. Если вы записывались с другого устройства, позвоните в салон.';
          return;
        }
        myBookingsMessage.hidden = true;
        var html = myNotice ? '<p class="my-bookings__notice">' + escapeHtml(myNotice) + '</p>' : '';
        myOrders.forEach(function (order) {
          var statusClass = String(order.status || '').replace(/[^a-z]/g, '');
          html += '<article class="my-booking">';
          html += '<div class="my-booking__head">';
          html += '<span class="my-booking__status my-booking__status--' + statusClass + '">' + escapeHtml(order.status_label || order.status) + '</span>';
          html += '<span class="my-booking__price">' + formatMoney(order.price) + ' ₸</span>';
          html += '</div>';
          html += '<h3>' + escapeHtml(order.service || 'Услуга') + '</h3>';
          if (Array.isArray(order.services) && order.services.length > 1) {
            html += '<ul class="my-booking__services">';
            order.services.forEach(function (item) {
              html += '<li><span>' + escapeHtml(item.name) +
                '</span><b>' + formatMoney(item.price) + ' ₸</b></li>';
            });
            html += '</ul>';
          }
          html += '<div class="my-booking__meta">';
          html += '<span>📅 ' + escapeHtml(formatDateHuman(order.date)) + ', <b>' + escapeHtml(order.time) + '</b></span>';
          html += '<span>👨‍💈 ' + escapeHtml(order.master || 'любой мастер') + '</span>';
          html += '<span>⏱ ' + escapeHtml(order.duration) + ' мин</span>';
          html += '</div>';
          if (order.comment) html += '<p class="my-booking__comment">' + escapeHtml(order.comment) + '</p>';
          if (order.needs_attention) {
            html += '<p class="my-booking__attention">⚠️ ' + escapeHtml(order.attention_reason || 'Запись требует внимания') + '. Свяжитесь с салоном.</p>';
          }
          if (myCancelId === order.id) {
            html += '<div class="my-booking__confirm">';
            html += '<span>Точно отменить запись?</span>';
            html += '<div class="my-booking__actions">';
            html += '<button class="btn btn--ghost btn--sm" type="button" data-my-action="cancel-yes" data-id="' + escapeHtml(order.id) + '">Да, отменить</button>';
            html += '<button class="btn btn--gold btn--sm" type="button" data-my-action="cancel-no" data-id="' + escapeHtml(order.id) + '">Нет, оставить</button>';
            html += '</div></div>';
          } else if (order.can_cancel || order.can_reschedule) {
            html += '<div class="my-booking__actions">';
            if (order.can_reschedule) {
              html += '<button class="btn btn--ghost btn--sm" type="button" data-my-action="reschedule" data-id="' + escapeHtml(order.id) + '">📅 Перенести</button>';
            }
            if (order.can_cancel) {
              html += '<button class="btn btn--ghost btn--sm" type="button" data-my-action="cancel" data-id="' + escapeHtml(order.id) + '">❌ Отменить</button>';
            }
            html += '</div>';
          }
          if (myRescheduleId === order.id) {
            html += '<div class="my-booking__reschedule">';
            html += '<label>Новая дата<select data-my-date="' + escapeHtml(order.id) + '">' + myDateOptions(myRescheduleDate) + '</select></label>';
            html += '<label>Новое время<select data-my-time="' + escapeHtml(order.id) + '">';
            if (myRescheduleLoading) {
              html += '<option value="">Загрузка…</option>';
            } else if (!myRescheduleSlots.length) {
              html += '<option value="">Нет мест</option>';
            } else {
              html += '<option value="">Выберите</option>';
              myRescheduleSlots.forEach(function (slot) {
                html += '<option value="' + escapeHtml(slot) + '">' + escapeHtml(slot) + '</option>';
              });
            }
            html += '</select></label>';
            html += '<div class="my-booking__actions">';
            html += '<button class="btn btn--gold btn--sm" type="button" data-my-action="reschedule-save" data-id="' + escapeHtml(order.id) + '"' + (myRescheduleLoading || !myRescheduleSlots.length ? ' disabled' : '') + '>Перенести</button>';
            html += '<button class="btn btn--ghost btn--sm" type="button" data-my-action="reschedule-close" data-id="' + escapeHtml(order.id) + '">Отмена</button>';
            html += '</div></div>';
          }
          html += '</article>';
        });
        myBookingsList.innerHTML = html;
      }

      function loadMyBookings(keepNotice) {
        if (!keepNotice) {
          myNotice = '';
          myCancelId = 0;
          myRescheduleId = 0;
          myRescheduleSlots = [];
          myRescheduleLoading = false;
        }
        clearMyError();
        var tokens = readMyTokens();
        myOrders = [];
        if (!tokens.length) {
          renderMyBookings();
          return;
        }
        myBookingsMessage.hidden = false;
        myBookingsMessage.textContent = 'Загружаем записи…';
        fetchJson(API_BASE + '/api/my-bookings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tokens: tokens })
        }, 8000).then(function (result) {
          if (result.data && result.data.ok && Array.isArray(result.data.orders)) {
            myOrders = result.data.orders.filter(function (order) {
              return order.status === 'new' || order.status === 'confirmed';
            });
            renderMyBookings();
          } else {
            myBookingsMessage.textContent = 'Не удалось загрузить записи.';
            showMyError((result.data && result.data.error) || 'Сервер не ответил.');
          }
        }).catch(function () {
          myBookingsMessage.textContent = 'Не удалось загрузить записи.';
          showMyError('Проверьте интернет и попробуйте ещё раз.');
        });
      }

      function loadMySlots(orderId, day) {
        myRescheduleSlots = [];
        myRescheduleLoading = true;
        myRescheduleDate = day;
        renderMyBookings();
        fetchJson(API_BASE + '/api/my-bookings/slots', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tokens: readMyTokens(), order_id: orderId, date: day })
        }, 6000).then(function (result) {
          if (myRescheduleId !== orderId || myRescheduleDate !== day) return;
          myRescheduleLoading = false;
          if (result.data && result.data.ok && Array.isArray(result.data.slots)) {
            myRescheduleSlots = result.data.slots;
          } else {
            showMyError((result.data && result.data.error) || 'Не удалось получить время.');
          }
          renderMyBookings();
        }).catch(function () {
          if (myRescheduleId !== orderId || myRescheduleDate !== day) return;
          myRescheduleLoading = false;
          showMyError('Не удалось получить свободное время.');
          renderMyBookings();
        });
      }

      function cancelMyOrder(orderId) {
        fetchJson(API_BASE + '/api/my-bookings/cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tokens: readMyTokens(), order_id: orderId })
        }, 6000).then(function (result) {
          if (result.data && result.data.ok) {
            myNotice = 'Запись отменена.';
            myCancelId = 0;
            loadMyBookings(true);
          } else {
            showMyError((result.data && result.data.error) || 'Не удалось отменить запись.');
          }
        }).catch(function () { showMyError('Не удалось отменить запись.'); });
      }

      function saveMyReschedule(orderId) {
        var dateSelect = myBookingsList.querySelector('[data-my-date="' + orderId + '"]');
        var timeSelect = myBookingsList.querySelector('[data-my-time="' + orderId + '"]');
        var day = dateSelect ? dateSelect.value : '';
        var time = timeSelect ? timeSelect.value : '';
        if (!day || !time) {
          showMyError('Выберите новую дату и время.');
          return;
        }
        fetchJson(API_BASE + '/api/my-bookings/reschedule', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tokens: readMyTokens(), order_id: orderId, date: day, time: time })
        }, 8000).then(function (result) {
          if (result.data && result.data.ok) {
            myNotice = 'Запись перенесена.';
            myRescheduleId = 0;
            loadMyBookings(true);
          } else {
            showMyError((result.data && result.data.error) || 'Не удалось перенести запись.');
          }
        }).catch(function () { showMyError('Не удалось перенести запись.'); });
      }

      if (myBookingsList) {
        myBookingsList.addEventListener('click', function (event) {
          var btn = event.target.closest ? event.target.closest('[data-my-action]') : null;
          if (!btn) return;
          var action = btn.getAttribute('data-my-action');
          var orderId = Number(btn.getAttribute('data-id') || 0);
          if (action === 'cancel') {
            myCancelId = orderId;
            myRescheduleId = 0;
            renderMyBookings();
          } else if (action === 'cancel-no') {
            myCancelId = 0;
            renderMyBookings();
          } else if (action === 'cancel-yes') {
            cancelMyOrder(orderId);
          } else if (action === 'reschedule') {
            myCancelId = 0;
            myRescheduleId = orderId;
            myRescheduleDate = isoDay(1);
            myRescheduleSlots = [];
            loadMySlots(orderId, myRescheduleDate);
          } else if (action === 'reschedule-close') {
            myRescheduleId = 0;
            myRescheduleSlots = [];
            renderMyBookings();
          } else if (action === 'reschedule-save') {
            saveMyReschedule(orderId);
          }
        });

        myBookingsList.addEventListener('change', function (event) {
          var select = event.target;
          if (!select || !select.matches || !select.matches('[data-my-date]')) return;
          var orderId = Number(select.getAttribute('data-my-date') || 0);
          loadMySlots(orderId, select.value);
        });
      }

      function updateMyBookingsAlert(orders) {
        if (!myBookingsAlert) return;
        var attention = (orders || []).some(function (order) { return order.needs_attention; });
        myBookingsAlert.hidden = !attention || myBookingsOpen;
      }

      function checkMyBookingsAlert() {
        var tokens = readMyTokens();
        if (!tokens.length) {
          if (myBookingsAlert) myBookingsAlert.hidden = true;
          return;
        }
        fetchJson(API_BASE + '/api/my-bookings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tokens: tokens })
        }, 8000).then(function (result) {
          if (result.data && result.data.ok && Array.isArray(result.data.orders)) {
            updateMyBookingsAlert(result.data.orders);
          }
        }).catch(function () {});
      }

      function openMyBookings(event) {
        if (event) event.preventDefault();
        myBookingsLastFocus = event && event.currentTarget ? event.currentTarget : document.activeElement;
        if (menuOpen) setMenu(false);
        if (!myBookingsModal) return;
        if (myBookingsAlert) myBookingsAlert.hidden = true;
        clearMyError();
        myBookingsModal.hidden = false;
        window.requestAnimationFrame(function () { myBookingsModal.classList.add('is-open'); });
        lockScroll('mybookings');
        myBookingsOpen = true;
        loadMyBookings();
        window.setTimeout(function () {
          var close = myBookingsModal.querySelector('[data-my-close]');
          if (close) close.focus({ preventScroll: true });
        }, 300);
      }

      function closeMyBookings() {
        if (!myBookingsModal || !myBookingsOpen) return;
        myBookingsModal.classList.remove('is-open');
        unlockScroll('mybookings');
        myBookingsOpen = false;
        window.setTimeout(function () {
          if (!myBookingsOpen) myBookingsModal.hidden = true;
          if (myBookingsLastFocus && myBookingsLastFocus.getClientRects().length) {
            myBookingsLastFocus.focus({ preventScroll: true });
          }
          myBookingsLastFocus = null;
        }, 380);
      }

      if (myBookingsModal) {
        myBookingsModal.addEventListener('keydown', function (event) {
          if (event.key !== 'Tab') return;
          var focusable = Array.prototype.filter.call(
            myBookingsModal.querySelectorAll('a[href],button:not([disabled]),input,select,textarea'),
            function (el) { return el.getClientRects().length > 0; }
          );
          if (!focusable.length) return;
          var first = focusable[0];
          var last = focusable[focusable.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        });
      }

      var successMyBookings = document.getElementById('successMyBookings');
      if (successMyBookings) {
        successMyBookings.addEventListener('click', function () {
          closeModal();
          window.setTimeout(openMyBookings, 420);
        });
      }
      ['myBookingsBtn', 'myBookingsBtnMobile', 'myBookingsBtnFooter'].forEach(function (id) {
        var btn = document.getElementById(id);
        if (btn) btn.addEventListener('click', openMyBookings);
      });
      if (myBookingsModal) {
        myBookingsModal.querySelectorAll('[data-my-close]').forEach(function (el) {
          el.addEventListener('click', closeMyBookings);
        });
      }
      if (myBookingsAlert) {
        var alertOpen = document.getElementById('myBookingsAlertOpen');
        if (alertOpen) alertOpen.addEventListener('click', openMyBookings);
        myBookingsAlert.querySelectorAll('[data-alert-close]').forEach(function (el) {
          el.addEventListener('click', function () { myBookingsAlert.hidden = true; });
        });
      }

      /* ---------- Динамический контент с сервера ---------- */
      function renderServices(services) {
        var grid = document.getElementById('servicesGrid');
        if (!grid) return;
        if (!services || !services.length) {
          grid.innerHTML = '<p class="services__empty">Список услуг обновляется. Позвоните нам, чтобы записаться.</p>';
          return;
        }
        grid.innerHTML = services.map(function (service, index) {
          var number = String(index + 1).padStart(2, '0');
          var photo = service.photo_url
            ? '<span class="service__photo"><img src="' + escapeHtml(service.photo_url) + '" alt="' + escapeHtml(service.name) + '" loading="lazy" decoding="async"></span>'
            : '';
          var description = service.description ? '<p>' + escapeHtml(service.description) + '</p>' : '';
          return '' +
            '<article class="service">' +
              '<a class="service__link" href="#contacts" data-booking data-service="' + escapeHtml(service.name) + '" data-service-id="' + escapeHtml(service.id) + '" aria-label="Записаться на ' + escapeHtml(service.name) + ' — ' + formatMoney(service.price) + ' ₸">' +
                photo +
                '<div class="service__top"><span class="service__num">' + number + '</span><span>' + escapeHtml(service.duration) + ' минут</span></div>' +
                '<h3>' + escapeHtml(service.name) + '</h3>' +
                description +
                '<div class="service__bottom">' +
                  '<span class="service__price">' + formatMoney(service.price) + ' <small>₸</small></span>' +
                  '<span class="service__arrow" aria-hidden="true"><svg viewBox="0 0 16 16" fill="none"><path d="M2 8h11M9 4l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span>' +
                '</div>' +
              '</a>' +
            '</article>';
        }).join('');
      }

      function renderServicePickerFromData() {
        renderServicePicker();
        updateServiceHint();
      }

      function renderMarquee(services) {
        var names = (services || []).map(function (service) { return service.name; }).filter(Boolean);
        if (!names.length) return;
        var html = names.map(function (name, index) {
          var label = escapeHtml(name);
          if (index % 2 === 1) label = '<em>' + label + '</em>';
          return '<span class="marquee__item">' + label + '</span><span class="marquee__star">✦</span>';
        }).join('');
        var groupA = document.getElementById('marqueeGroupA');
        var groupB = document.getElementById('marqueeGroupB');
        if (groupA) groupA.innerHTML = html;
        if (groupB) groupB.innerHTML = html;
      }

      function renderMasters(masters) {
        var grid = document.getElementById('mastersGrid');
        if (!grid) return;
        if (!masters || !masters.length) {
          grid.innerHTML = '<p class="services__empty">Мастера появятся здесь. Позвоните нам, чтобы записаться.</p>';
          return;
        }
        grid.innerHTML = masters.map(function (master) {
          var hasPhoto = !!master.photo_url;
          var media = hasPhoto
            ? '<img src="' + escapeHtml(master.photo_url) + '" alt="' + escapeHtml(master.name) + ', барбер" loading="lazy" decoding="async">'
            : '<span>' + escapeHtml(initialsFromName(master.name)) + '</span>';
          return '' +
            '<article class="master">' +
              '<div class="master__media' + (hasPhoto ? ' master__media--photo' : ' master__media--empty') + '" data-initials="' + escapeHtml(initialsFromName(master.name)) + '">' + media + '</div>' +
              '<div class="master__body">' +
                '<span class="master__role">Барбер</span>' +
                '<h3>' + escapeHtml(master.name) + '</h3>' +
                '<p>' + escapeHtml(master.description || 'Мастер барбершопа.') + '</p>' +
                (master.hours ? '<span class="master__hours">' + escapeHtml(master.hours) + '</span>' : '') +
                '<a class="btn btn--ghost btn--sm" href="#contacts" data-booking data-master="' + escapeHtml(master.name) + '" data-master-id="' + escapeHtml(master.id) + '">Записаться</a>' +
              '</div>' +
            '</article>';
        }).join('');
        grid.querySelectorAll('.master__media--photo img').forEach(function (img) {
          img.addEventListener('error', function () {
            var media = img.parentElement;
            if (!media) return;
            media.classList.remove('master__media--photo');
            media.classList.add('master__media--empty');
            media.innerHTML = '<span>' + escapeHtml(media.getAttribute('data-initials') || 'Б') + '</span>';
          });
        });
      }

      function rebuildMasterSelect(masters) {
        if (!masterSelect) return;
        var current = masterSelect.value;
        var html = '<option value="">Любой свободный</option>';
        (masters || []).forEach(function (master) {
          html += '<option value="' + escapeHtml(master.id) + '">' + escapeHtml(master.name) + '</option>';
        });
        masterSelect.innerHTML = html;
        if (current) {
          var exists = false;
          Array.prototype.forEach.call(masterSelect.options, function (option) {
            if (option.value === current) exists = true;
          });
          if (exists) masterSelect.value = current;
          else masterSelect.value = '';
        }
        updateMasterHint();
      }

      function renderGallery(items) {
        var grid = document.querySelector('.gallery__grid');
        if (!grid) return;
        if (!items || !items.length) {
          grid.innerHTML = '<p class="services__empty">Фотографии скоро появятся.</p>';
          return;
        }
        grid.innerHTML = items.map(function (item, index) {
          var gradient = (index % 6) + 1;
          var image = item.image_url
            ? '<div class="shot__media"><img class="shot__img" src="' + escapeHtml(item.image_url) + '" alt="' + escapeHtml(item.caption || 'Фото барбершопа') + '" loading="lazy" decoding="async"></div>'
            : '<div class="shot__media" aria-hidden="true"></div>';
          var caption = item.caption || 'фото';
          var interactive = item.image_url
            ? ' data-full-src="' + escapeHtml(item.image_url) + '"' +
              ' data-caption="' + escapeHtml(caption) + '"' +
              ' role="button" tabindex="0" aria-label="Открыть фото: ' + escapeHtml(caption) + '"'
            : '';
          return '' +
            '<figure class="shot shot--' + gradient + '"' + interactive + '>' +
              image +
              '<span class="shot__num" aria-hidden="true">' + String(index + 1).padStart(2, '0') + '</span>' +
              '<figcaption class="shot__tag">' + escapeHtml(item.caption || 'фото') + '</figcaption>' +
            '</figure>';
        }).join('');
      }

      function renderReviews(reviews) {
        var grid = document.querySelector('.reviews__grid');
        if (!grid) return;
        if (!reviews || !reviews.length) {
          grid.innerHTML = '<article class="review"><blockquote>Пока нет отзывов. Станьте первым гостем, кто его оставит.</blockquote></article>';
          return;
        }
        grid.innerHTML = reviews.map(function (review) {
          var rating = Math.max(1, Math.min(5, parseInt(review.rating, 10) || 5));
          var stars = '★'.repeat(rating) + '<span class="review__stars-off">' + '★'.repeat(5 - rating) + '</span>';
          return '' +
            '<article class="review">' +
              '<div class="review__stars" aria-label="Оценка ' + rating + ' из 5">' + stars + '</div>' +
              '<blockquote>' + escapeHtml(review.text) + '</blockquote>' +
              '<footer>' +
                '<span class="review__avatar" aria-hidden="true">' + escapeHtml(initialsFromName(review.name)) + '</span>' +
                '<div class="review__who"><strong>' + escapeHtml(review.name) + '</strong><span>' + escapeHtml(review.source) + '</span></div>' +
              '</footer>' +
            '</article>';
        }).join('');
      }

      function fitHeaderLogo() {
        var inner = document.querySelector('.header__inner');
        var logo = inner ? inner.querySelector('.logo') : null;
        var word = logo ? logo.querySelector('.logo__word') : null;
        if (!inner || !logo || !word) return;

        word.style.fontSize = '';
        word.style.letterSpacing = '';
        word.style.maxWidth = '';
        logo.style.maxWidth = '';

        var nav = inner.querySelector('.nav');
        var actions = inner.querySelector('.header__actions');
        var navVisible = !!(nav && getComputedStyle(nav).display !== 'none');
        var computed = getComputedStyle(inner);
        var gap = parseFloat(computed.columnGap || computed.gap) || 16;
        var padLeft = parseFloat(computed.paddingLeft) || 0;
        var padRight = parseFloat(computed.paddingRight) || 0;
        var reserve = gap * (navVisible ? 2 : 1);
        var fixed = (actions ? actions.getBoundingClientRect().width : 0);
        if (navVisible) fixed += nav.getBoundingClientRect().width;
        var available = Math.floor(
          inner.clientWidth - padLeft - padRight - fixed - reserve - 6
        );
        if (available <= 0) return;

        var clone = word.cloneNode(true);
        clone.style.cssText = 'position:absolute;left:-9999px;top:0;visibility:hidden;' +
          'white-space:nowrap;max-width:none;font-size:19px;letter-spacing:.24em;';
        document.body.appendChild(clone);
        var natural = clone.getBoundingClientRect().width;
        clone.parentNode.removeChild(clone);

        if (natural > available && natural > 0) {
          var size = Math.max(10, 19 * (available / natural));
          var tracking = Math.max(0.08, 0.24 * (available / natural));
          word.style.fontSize = size.toFixed(2) + 'px';
          word.style.letterSpacing = tracking.toFixed(3) + 'em';
        }
        logo.style.maxWidth = available + 'px';
        word.style.maxWidth = available + 'px';
      }

      function applyContacts(data) {
        var c = data.contacts || {};
        var brand = data.brand || 'ЛЕЗВИЕ';
        var city = data.city || 'Алматы';
        var whatsapp = onlyDigits(c.whatsapp) || onlyDigits(c.phone_digits) || '77000000000';

        document.querySelectorAll('.logo__word').forEach(function (el) {
          el.innerHTML = escapeHtml(brand) + '<span class="logo__dot">.</span>';
        });
        document.querySelectorAll('.logo').forEach(function (el) {
          el.setAttribute('aria-label', brand + ' — в начало страницы');
        });
        document.querySelectorAll('.logo__sub').forEach(function (el) {
          el.textContent = 'barbershop · ' + city;
        });
        fitHeaderLogo();

        var heroEyebrow = document.getElementById('heroEyebrow');
        if (heroEyebrow) heroEyebrow.textContent = 'Барбершоп · ' + city + ' · с 2021';

        var heroAddress = document.getElementById('heroAddress');
        if (heroAddress) heroAddress.innerHTML = '<b>' + escapeHtml(c.address) + '</b> · ' + escapeHtml(city);

        var heroHours = document.getElementById('heroHours');
        if (heroHours) {
          var match = String(c.hours || '').match(/^(.*?)(\d{1,2}:\d{2}.*)$/);
          heroHours.innerHTML = match
            ? escapeHtml(match[1]) + '<b>' + escapeHtml(match[2]) + '</b>'
            : escapeHtml(c.hours || '');
        }

        var menuAddress = document.getElementById('menuAddress');
        if (menuAddress) {
          menuAddress.innerHTML = '<b>' + escapeHtml(c.address || '') + '</b> · ' + escapeHtml(city);
        }
        var menuHours = document.getElementById('menuHours');
        if (menuHours) menuHours.textContent = c.hours || '10:00–21:00';

        var addressEl = document.getElementById('contactAddress');
        if (addressEl) {
          addressEl.innerHTML = escapeHtml(c.address || '') +
            (c.address_note ? ' <small>' + escapeHtml(c.address_note) + '</small>' : '');
        }
        var hoursEl = document.getElementById('contactHours');
        if (hoursEl) {
          hoursEl.innerHTML = escapeHtml(c.hours || '') +
            (c.hours_note ? ' <small>' + escapeHtml(c.hours_note) + '</small>' : '');
        }

        var phone = c.phone || '';
        var phoneDigits = onlyDigits(phone);
        var contactPhone = document.getElementById('contactPhone');
        if (contactPhone) {
          contactPhone.textContent = phone || '—';
          contactPhone.href = 'tel:+' + phoneDigits;
        }
        var modalPhone = document.getElementById('modalPhone');
        if (modalPhone) {
          modalPhone.textContent = phone || '—';
          modalPhone.href = 'tel:+' + phoneDigits;
        }

        var waFloat = document.getElementById('waFloat');
        var waContact = document.getElementById('waContact');
        if (waFloat) waFloat.href = 'https://wa.me/' + whatsapp;
        if (waContact) waContact.href = 'https://wa.me/' + whatsapp;

        var routeBtn = document.getElementById('routeBtn');
        if (routeBtn) {
          if (c.twogis_url && /^https?:\/\//i.test(c.twogis_url)) {
            routeBtn.href = c.twogis_url;
            routeBtn.hidden = false;
          } else {
            routeBtn.hidden = true;
          }
        }

        var insta = document.getElementById('instagramLink');
        if (insta) {
          if (c.instagram) {
            insta.hidden = false;
            insta.href = c.instagram;
            var instaLabel = document.getElementById('instagramLabel');
            if (instaLabel) instaLabel.textContent = c.instagram_label || '@instagram';
          } else {
            insta.hidden = true;
          }
        }

        var footerPlace = document.getElementById('footerPlace');
        if (footerPlace) footerPlace.textContent = city + ' · ' + (c.address || '');
        var footerBrand = document.getElementById('footerBrandText');
        if (footerBrand) footerBrand.textContent = 'Мужские стрижки, борода и бритьё в центре ' + city + '. С 2021 года.';
        var copyright = document.getElementById('copyrightBrand');
        if (copyright) copyright.textContent = brand;

        var mapBadge = document.getElementById('mapBadge');
        if (mapBadge) mapBadge.innerHTML = '<i></i> ' + escapeHtml(brand) + ' · ' + escapeHtml(c.address || '');
        var mapCity = document.getElementById('mapCity');
        if (mapCity) mapCity.textContent = city;
        var mapCard = document.getElementById('mapCard');
        if (mapCard) mapCard.setAttribute('aria-label', 'Стилизованная карта: барбершоп ' + brand + ', ' + (c.address || '') + ', ' + city);

        document.title = brand + ' — барбершоп в ' + city + ' | Стрижка, борода, бритьё';
        var description = document.querySelector('meta[name="description"]');
        if (description) {
          description.content = brand + ' в ' + city + ': мужские стрижки, борода и бритьё. ' +
            (c.address || '') + ', ' + (c.hours || '') + '. Запись онлайн.';
        }
        var ogSiteName = document.querySelector('meta[property="og:site_name"]');
        if (ogSiteName) ogSiteName.content = brand + ' — барбершоп';
        var ogUrl = document.querySelector('meta[property="og:url"]');
        if (ogUrl && /^https?:/i.test(location.protocol)) ogUrl.content = location.origin + '/';
        var ogTitle = document.querySelector('meta[property="og:title"]');
        if (ogTitle) ogTitle.content = brand + ' — барбершоп в ' + city;
        var ogDescription = document.querySelector('meta[property="og:description"]');
        if (ogDescription) ogDescription.content = 'Мужские стрижки, борода и бритьё в центре ' + city + '. Запись онлайн.';
        var twitterTitle = document.querySelector('meta[name="twitter:title"]');
        if (twitterTitle) twitterTitle.content = brand + ' — барбершоп в ' + city;
        var twitterDescription = document.querySelector('meta[name="twitter:description"]');
        if (twitterDescription) twitterDescription.content = 'Мужские стрижки, борода и бритьё в центре ' + city + '. Строго по записи.';

        var schemaEl = document.getElementById('salonSchema');
        if (schemaEl) {
          try {
            var schema = JSON.parse(schemaEl.textContent);
            schema.name = brand;
            schema.description = brand + ' в ' + city + ': мужские стрижки, борода и бритьё.';
            schema.telephone = c.phone || '';
            schema.address = schema.address || {};
            schema.address.streetAddress = c.address || '';
            schema.address.addressLocality = city;
            if (/^https?:/i.test(location.protocol)) schema.url = location.origin + '/';
            if (c.instagram) schema.sameAs = [c.instagram];
            else delete schema.sameAs;
            schemaEl.textContent = JSON.stringify(schema);
          } catch (error) {
            /* JSON-LD не критичен для работы сайта. */
          }
        }
      }

      function renderWhy(items) {
        var grid = document.getElementById('whyGrid');
        if (!grid) return;
        if (!items || !items.length) {
          grid.innerHTML = '<p class="services__empty">Скоро расскажем, почему сюда возвращаются.</p>';
          return;
        }
        grid.innerHTML = items.map(function (item) {
          return '' +
            '<article class="why__item">' +
              '<div class="why__icon" aria-hidden="true">' + escapeHtml(item.icon || '✦') + '</div>' +
              '<h3>' + escapeHtml(item.title) + '</h3>' +
              '<p>' + escapeHtml(item.text) + '</p>' +
            '</article>';
        }).join('');
      }

      function applyBookingSettings(data) {
        var settings = data.settings || {};
        var hasMasters = Array.isArray(data.masters) ? data.masters.length > 0 : true;
        bookingEnabled = !!settings.booking_enabled && (data.services || []).length > 0 && hasMasters;
        syncBookingState();
        if (modalOpen && !bookingEnabled) {
          showBookingError('Онлайн-запись временно недоступна. Позвоните нам — подберём время вручную.');
        }
      }

      function statLabelHtml(value) {
        return String(value || '')
          .split('|')
          .map(function (part) { return escapeHtml(part); })
          .join('<br>');
      }

      function applyStats(stats) {
        if (!Array.isArray(stats) || !statsGrid) return;
        var signature = JSON.stringify(stats);
        if (signature === statsSignature) return;
        statsSignature = signature;

        if (!stats.length) {
          statsGrid.innerHTML = '';
          if (statsSection) statsSection.hidden = true;
          return;
        }
        if (statsSection) statsSection.hidden = false;

        statsGrid.innerHTML = stats.map(function (item) {
          var numeric = item.numeric === true || typeof item.value === 'number';
          var value = numeric ? Number(item.value) : String(item.value == null ? '' : item.value);
          var decimals = Number(item.decimals) || 0;
          if (numeric && !isFinite(value)) {
            numeric = false;
            value = String(item.value == null ? '' : item.value);
          }
          var numberHtml;
          if (numeric) {
            numberHtml =
              '<span data-count="' + value + '" data-decimals="' + decimals + '">' +
                formatNumber(value, decimals) +
              '</span>' +
              (item.plus ? '<span class="stat__plus">+</span>' : '');
          } else {
            numberHtml = '<span>' + escapeHtml(value) + '</span>';
          }
          return '' +
            '<div class="stat' + (numeric ? '' : ' stat--text') + '">' +
              '<div class="stat__num' + (numeric ? '' : ' stat__num--text') + '">' +
                numberHtml +
              '</div>' +
              '<div class="stat__label">' + statLabelHtml(item.label) + '</div>' +
            '</div>';
        }).join('');

        initCounters(statsGrid);
      }

      function applySiteData(data) {
        siteData = data;
        var previousMaster = masterSelect ? masterSelect.value : '';
        siteServices = Array.isArray(data.services) ? data.services : [];
        siteMasters = Array.isArray(data.masters) ? data.masters : [];
        renderServices(siteServices);
        renderMarquee(siteServices);
        renderServicePickerFromData();
        renderMasters(siteMasters);
        rebuildMasterSelect(siteMasters);
        renderGallery(data.gallery || []);
        renderReviews(data.reviews || []);
        if (Array.isArray(data.why)) renderWhy(data.why);
        applyStats(data.stats || []);
        applyContacts(data);
        applyBookingSettings(data);
        updateServiceHint();
        updateMasterHint();
        if (modalOpen) loadSlots();
      }

      function loadSiteData() {
        fetchJson(API_BASE + '/api/site', null, 4500).then(function (result) {
          if (result.response && result.response.ok && result.data) {
            applySiteData(result.data);
          }
        }).catch(function () {
          /* Сайт остаётся на статичном контенте — это нормально. */
        });
      }

      function syncThemeColor() {
        var meta = document.querySelector('meta[name="theme-color"]');
        if (!meta) return;
        var bg = getComputedStyle(document.documentElement)
          .getPropertyValue('--bg').trim();
        if (bg) meta.content = bg;
      }

      var logoFitTimer = null;
      window.addEventListener('resize', function () {
        window.clearTimeout(logoFitTimer);
        logoFitTimer = window.setTimeout(fitHeaderLogo, 120);
      });
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(fitHeaderLogo).catch(function () {});
      }
      fitHeaderLogo();
      syncThemeColor();

      buildDateOptions();
      renderServicePicker();
      setChannel('telegram');
      updateServiceHint();
      // Данные сайта загружаются один раз при открытии/обновлении страницы.
      // Никаких фоновых запросов к базе каждую минуту — это важно для Neon Free.
      loadSiteData();
      checkMyBookingsAlert();

      var yearEl = document.getElementById('year');
      if (yearEl) yearEl.textContent = String(new Date().getFullYear());
    })();