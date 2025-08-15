(function() {
    'use strict';
    
    // Check if we're in an Odoo environment with the new module system
    if (typeof odoo !== 'undefined' && odoo.define) {
        odoo.define('leonix_video_translator.download_progress', function (require) {
            var publicWidget = require('web.public.widget');
            var ajax = require('web.ajax');
            
            return createVideoDownloadProgress(publicWidget, ajax);
        });
    } else {
        // Fallback for environments where odoo.define is not available
        document.addEventListener('DOMContentLoaded', function() {
            // Use jQuery and simple AJAX if available
            if (typeof $ !== 'undefined') {
                var simpleAjax = {
                    jsonRpc: function(url, method, params) {
                        return $.ajax({
                            url: url,
                            type: 'POST',
                            dataType: 'json',
                            contentType: 'application/json',
                            data: JSON.stringify({
                                jsonrpc: '2.0',
                                method: 'call',
                                params: params,
                                id: new Date().getTime()
                            })
                        }).then(function(response) {
                            return response.result;
                        });
                    }
                };
                
                // Simple widget-like object
                var SimpleWidget = {
                    extend: function(props) {
                        function Widget() {
                            this.progressInterval = null;
                            this.videoId = null;
                            if (props.init) props.init.call(this);
                        }
                        
                        for (var key in props) {
                            Widget.prototype[key] = props[key];
                        }
                        
                        return Widget;
                    }
                };
                
                var VideoDownloadProgressClass = createVideoDownloadProgress(SimpleWidget, simpleAjax);
                
                // Initialize widgets
                $('.o_portal_video_download').each(function() {
                    var widget = new VideoDownloadProgressClass();
                    widget.$el = $(this);
                    if (widget.start) widget.start.call(widget);
                });
            }
        });
    }
    
    // Common function to create the video download progress functionality
    function createVideoDownloadProgress(Widget, ajax) {
    
    var VideoDownloadProgress = Widget.extend({
        selector: '.o_portal_video_download',
        events: {
            'submit .download-form': '_onDownloadSubmit',
        },
        
        init: function () {
            if (this._super) this._super.apply(this, arguments);
            this.progressInterval = null;
            this.videoId = null;
        },
        
        start: function () {
            var self = this;
            this.videoId = this.$el.data('video-id');
            
            // Check if video is currently downloading
            if (this.$el.find('.progress').length > 0) {
                this._startProgressTracking();
            }
            
            // Set up event handlers manually if needed
            var $form = this.$el.find('.download-form');
            if ($form.length > 0) {
                $form.on('submit', function(ev) {
                    self._onDownloadSubmit(ev);
                });
            }
            
            if (this._super) return this._super.apply(this, arguments);
        },
        
        destroy: function () {
            if (this.progressInterval) {
                clearInterval(this.progressInterval);
            }
            if (this._super) this._super.apply(this, arguments);
        },
        
        _onDownloadSubmit: function (ev) {
            var self = this;
            ev.preventDefault();
            var $form = $(ev.currentTarget);
            var $button = $form.find('button');
            
            // Disable button and show loading
            $button.prop('disabled', true);
            $button.html('<i class="fa fa-spinner fa-spin"></i> Starting Download...');
            
            // Submit form
            $form[0].submit();
            
            // Start progress tracking after a short delay
            setTimeout(function () {
                self._startProgressTracking();
            }, 2000);
        },
        
        _startProgressTracking: function () {
            var self = this;
            
            if (this.progressInterval) {
                clearInterval(this.progressInterval);
            }
            
            this.progressInterval = setInterval(function () {
                self._checkProgress();
            }, 2000); // Check every 2 seconds
        },
        
        _checkProgress: function () {
            var self = this;
            if (!this.videoId) return;
            
            ajax.jsonRpc('/my/video-translations/' + this.videoId + '/progress', 'call', {})
                .then(function (result) {
                    if (result.success) {
                        self._updateProgress(result);
                        
                        // If download is complete, reload page
                        if (result.state === 'downloaded') {
                            clearInterval(self.progressInterval);
                            self._showCompletionNotification();
                            setTimeout(function () {
                                window.location.reload();
                            }, 1500);
                        } else if (result.state === 'failed') {
                            clearInterval(self.progressInterval);
                            self._showErrorNotification();
                            setTimeout(function () {
                                window.location.reload();
                            }, 2000);
                        }
                    }
                })
                .catch(function (error) {
                    console.error('Progress check failed:', error);
                });
        },
        
        _updateProgress: function (data) {
            var $progressBar = this.$el.find('.progress-bar');
            var $progressText = $progressBar.find('span');
            var $speedElement = this.$el.find('[data-progress-speed]');
            var $etaElement = this.$el.find('[data-progress-eta]');
            
            if ($progressBar.length > 0) {
                $progressBar.css('width', data.progress + '%');
                $progressBar.attr('aria-valuenow', data.progress);
                if ($progressText.length > 0) {
                    $progressText.text(data.progress.toFixed(1) + '%');
                }
            }
            
            if (data.speed && $speedElement.length > 0) {
                $speedElement.text(data.speed);
            }
            
            if (data.eta && $etaElement.length > 0) {
                $etaElement.text(data.eta);
            }
        },
        
        _showCompletionNotification: function () {
            this._showNotification(
                'Video Download Complete!', 
                'Your video has been successfully downloaded and is ready to watch.', 
                'success'
            );
        },
        
        _showErrorNotification: function () {
            this._showNotification(
                'Download Failed', 
                'There was an error downloading your video. Please try again.', 
                'error'
            );
        },
        
        _showNotification: function (title, message, type) {
            var alertClass = type === 'success' ? 'alert-success' : 'alert-danger';
            var icon = type === 'success' ? 'fa-check-circle' : 'fa-exclamation-triangle';
            
            var notification = $('<div class="alert ' + alertClass + ' alert-dismissible fade show notification-popup" style="position: fixed; top: 20px; right: 20px; z-index: 9999; min-width: 300px;">' +
                '<i class="fa ' + icon + '"></i> <strong>' + title + '</strong><br>' +
                message +
                '<button type="button" class="btn-close" data-bs-dismiss="alert"></button>' +
                '</div>');
            
            $('body').append(notification);
            
            // Auto-remove after 5 seconds
            setTimeout(function () {
                notification.fadeOut(function () {
                    notification.remove();
                });
            }, 5000);
        }
    });
    
    // Register the widget if we have publicWidget registry
    if (typeof Widget.registry !== 'undefined') {
        Widget.registry.VideoDownloadProgress = VideoDownloadProgress;
    }
    
    return VideoDownloadProgress;
    }
})();
