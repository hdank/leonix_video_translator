odoo.define('leonix_video_translator.portal', function (require) {
    'use strict';

    var publicWidget = require('web.public.widget');
    var ajax = require('web.ajax');

    publicWidget.registry.VideoProcessingStatus = publicWidget.Widget.extend({
        selector: '.o_portal_video_download',
        events: {
            'click .btn-refresh-status': '_onRefreshStatus',
        },

        start: function () {
            this._super.apply(this, arguments);
            this.videoId = this.$el.data('video-id');
            
            // Auto-refresh status every 10 seconds if processing is in progress
            this._startAutoRefresh();
            return Promise.resolve();
        },

        _startAutoRefresh: function () {
            var self = this;
            
            // Check if any processing is in progress
            var hasInProgress = this.$('.badge:contains("In Progress")').length > 0;
            
            if (hasInProgress) {
                this.refreshInterval = setInterval(function () {
                    self._refreshStatus();
                }, 10000); // Every 10 seconds
            }
        },

        _stopAutoRefresh: function () {
            if (this.refreshInterval) {
                clearInterval(this.refreshInterval);
                this.refreshInterval = null;
            }
        },

        _onRefreshStatus: function (ev) {
            ev.preventDefault();
            this._refreshStatus();
        },

        _refreshStatus: function () {
            var self = this;
            
            return ajax.jsonRpc('/my/video-translations/' + this.videoId + '/processing-status', 'call', {}).then(function (data) {
                if (data.success) {
                    // Update status badges
                    self._updateStatusBadge('transcription', data.transcription_status);
                    self._updateStatusBadge('translation', data.translation_status);
                    self._updateStatusBadge('dubbing', data.dubbing_status);
                    
                    // Update content areas
                    if (data.transcription_text && !$('#transcription-result').length) {
                        self._addTranscriptionResult(data.transcription_text);
                    }
                    
                    if (data.translation_text && !$('#translation-result').length) {
                        self._addTranslationResult(data.translation_text);
                    }
                    
                    if (data.has_dubbed_video && !$('#dubbed-video-result').length) {
                        // Reload page to show dubbed video
                        window.location.reload();
                    }
                    
                    // Stop auto-refresh if all processing is complete
                    var stillProcessing = data.transcription_status === 'in_progress' || 
                                        data.translation_status === 'in_progress' || 
                                        data.dubbing_status === 'in_progress';
                    
                    if (!stillProcessing) {
                        self._stopAutoRefresh();
                    }
                }
            });
        },

        _updateStatusBadge: function (type, status) {
            var $badge = this.$('.badge:contains("' + this._capitalizeFirst(type) + ':"))').parent().find('.badge').last();
            
            // Remove old classes and add new ones
            $badge.removeClass('bg-secondary bg-warning bg-success bg-danger');
            
            var badgeClass = 'bg-secondary';
            var statusText = 'Not Started';
            
            switch (status) {
                case 'in_progress':
                    badgeClass = 'bg-warning';
                    statusText = 'In Progress';
                    break;
                case 'completed':
                    badgeClass = 'bg-success';
                    statusText = 'Completed';
                    break;
                case 'failed':
                    badgeClass = 'bg-danger';
                    statusText = 'Failed';
                    break;
            }
            
            $badge.addClass(badgeClass).text(statusText);
        },

        _addTranscriptionResult: function (text) {
            var html = '<div id="transcription-result" class="mt-4">' +
                       '<h6><i class="fa fa-file-text"></i> Transcription Result:</h6>' +
                       '<div class="card"><div class="card-body">' +
                       '<div style="max-height: 200px; overflow-y: auto;">' + text + '</div>' +
                       '</div></div></div>';
            
            this.$('.card-body').append(html);
        },

        _addTranslationResult: function (text) {
            var html = '<div id="translation-result" class="mt-4">' +
                       '<h6><i class="fa fa-language"></i> Translation Result:</h6>' +
                       '<div class="card"><div class="card-body">' +
                       '<div style="max-height: 200px; overflow-y: auto;">' + text + '</div>' +
                       '</div></div></div>';
            
            this.$('.card-body').append(html);
        },

        _capitalizeFirst: function (str) {
            return str.charAt(0).toUpperCase() + str.slice(1);
        },

        destroy: function () {
            this._stopAutoRefresh();
            this._super.apply(this, arguments);
        },
    });

    return publicWidget.registry.VideoProcessingStatus;
});
