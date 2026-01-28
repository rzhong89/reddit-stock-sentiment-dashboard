const API_ENDPOINT = CONFIG.API_ENDPOINT;
const TICKERS_ENDPOINT = CONFIG.TICKERS_ENDPOINT;
const API_KEY = CONFIG.API_KEY;
let TICKERS = [];

const tickerSelect = document.getElementById('ticker-select');
const typeSelect = document.getElementById('type-select');
const lineChartCanvas = document.getElementById('sentiment-line-chart');
const barChartCanvas = document.getElementById('sentiment-bar-chart');
const postsTableDiv = document.getElementById('posts-table');

let sentimentLineChart;
let sentimentBarChart;

async function fetchTickers() {
    try {
        const response = await fetch(TICKERS_ENDPOINT, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Api-Key': API_KEY
            }
        });
        if (!response.ok) {
            throw new Error(`Failed to fetch tickers: ${response.status}`);
        }
        const data = await response.json();
        return data.tickers || [];
    } catch (error) {
        console.error('Error fetching tickers:', error);
        return ['AAPL', 'TSLA', 'AMZN', 'GOOGL', 'MSFT'];
    }
}

function populateTickerFilter() {
    TICKERS.forEach(ticker => {
        const option = document.createElement('option');
        option.value = ticker;
        option.textContent = ticker;
        tickerSelect.appendChild(option);
    });
}

async function fetchData(ticker = 'ALL', type = 'all') {
    try {
        const response = await fetch(`${API_ENDPOINT}?ticker=${ticker}&type=${type}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Api-Key': API_KEY
            }
        });
        if (!response.ok) {
            throw new Error(`API request failed with status ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching data:', error);
        if (error.message.includes('400')) {
            // Likely no data available for this ticker/filter combination
            return { trend_data: [], posts_data: [], metadata: { message: 'No data available for the selected filters' } };
        }
        alert('Failed to fetch sentiment data. Please check the console for details.');
        return { trend_data: [], posts_data: [], metadata: { message: 'Error loading data' } };
    }
}

function processData(apiResponse) {
    const trendData = apiResponse.trend_data || [];
    const postsData = apiResponse.posts_data || [];

    trendData.sort((a, b) => new Date(a.post_date) - new Date(b.post_date));

    const lineChartData = {
        labels: [...new Set(trendData.map(d => d.post_date))],
        datasets: [
            { label: 'Positive', data: [], borderColor: 'green', fill: false },
            { label: 'Negative', data: [], borderColor: 'red', fill: false },
            { label: 'Neutral', data: [], borderColor: 'gray', fill: false }
        ]
    };

    const barChartData = {
        'POSITIVE': 0,
        'NEGATIVE': 0,
        'NEUTRAL': 0
    };

    // New: Content type analysis
    const contentTypeData = {
        'INFORMATIVE': 0,
        'EMOTIONAL': 0
    };

    // New: Combined classification data
    const combinedData = {
        'POSITIVE_INFORMATIVE': 0,
        'POSITIVE_EMOTIONAL': 0,
        'NEGATIVE_INFORMATIVE': 0,
        'NEGATIVE_EMOTIONAL': 0,
        'NEUTRAL_INFORMATIVE': 0,
        'NEUTRAL_EMOTIONAL': 0
    };

    lineChartData.labels.forEach(date => {
        const dayData = trendData.filter(d => d.post_date === date);
        lineChartData.datasets[0].data.push(dayData.find(d => d.sentiment_type === 'POSITIVE')?.post_count || 0);
        lineChartData.datasets[1].data.push(dayData.find(d => d.sentiment_type === 'NEGATIVE')?.post_count || 0);
        lineChartData.datasets[2].data.push(dayData.find(d => d.sentiment_type === 'NEUTRAL')?.post_count || 0);
    });

    trendData.forEach(d => {
        barChartData[d.sentiment_type] = (barChartData[d.sentiment_type] || 0) + parseInt(d.post_count, 10);
        
        // Process content type data if available
        if (d.content_type) {
            contentTypeData[d.content_type] = (contentTypeData[d.content_type] || 0) + parseInt(d.post_count, 10);
            
            // Process combined classification
            const combinedKey = `${d.sentiment_type}_${d.content_type}`;
            if (combinedData.hasOwnProperty(combinedKey)) {
                combinedData[combinedKey] += parseInt(d.post_count, 10);
            }
        }
    });

    return { lineChartData, barChartData, contentTypeData, combinedData, postsData };
}

function renderDashboard(processedData) {
    // Check if there's no data and show a friendly message
    if (!processedData.postsData || processedData.postsData.length === 0) {
        if (sentimentLineChart) sentimentLineChart.destroy();
        if (sentimentBarChart) sentimentBarChart.destroy();
        
        // Display no data message
        const noDataMessage = '<div style="text-align: center; padding: 2rem; color: #666;"><h3>No data available</h3><p>No posts found for the selected ticker and filters. Try selecting a different ticker or check back later.</p></div>';
        postsTableDiv.innerHTML = noDataMessage;
        
        // Clear chart areas
        lineChartCanvas.getContext('2d').clearRect(0, 0, lineChartCanvas.width, lineChartCanvas.height);
        barChartCanvas.getContext('2d').clearRect(0, 0, barChartCanvas.width, barChartCanvas.height);
        return;
    }

    if (sentimentLineChart) sentimentLineChart.destroy();
    if (sentimentBarChart) sentimentBarChart.destroy();

    sentimentLineChart = new Chart(lineChartCanvas, {
        type: 'line',
        data: {
            labels: processedData.lineChartData.labels,
            datasets: [
                {
                    label: 'Positive',
                    data: processedData.lineChartData.datasets[0].data,
                    borderColor: '#00ff88',
                    backgroundColor: 'rgba(0, 255, 136, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#00ff88',
                    pointBorderColor: '#0a0e13',
                    pointBorderWidth: 2
                },
                {
                    label: 'Negative',
                    data: processedData.lineChartData.datasets[1].data,
                    borderColor: '#ff3366',
                    backgroundColor: 'rgba(255, 51, 102, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#ff3366',
                    pointBorderColor: '#0a0e13',
                    pointBorderWidth: 2
                },
                {
                    label: 'Neutral',
                    data: processedData.lineChartData.datasets[2].data,
                    borderColor: '#6b8caf',
                    backgroundColor: 'rgba(107, 140, 175, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#6b8caf',
                    pointBorderColor: '#0a0e13',
                    pointBorderWidth: 2
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: '#e8edf3',
                        font: {
                            family: "'JetBrains Mono', monospace",
                            size: 12
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        color: 'rgba(125, 141, 160, 0.1)',
                        borderColor: 'rgba(125, 141, 160, 0.2)'
                    },
                    ticks: {
                        color: '#7d8da0',
                        font: {
                            family: "'IBM Plex Mono', monospace",
                            size: 10
                        }
                    }
                },
                y: {
                    grid: {
                        color: 'rgba(125, 141, 160, 0.1)',
                        borderColor: 'rgba(125, 141, 160, 0.2)'
                    },
                    ticks: {
                        color: '#7d8da0',
                        font: {
                            family: "'IBM Plex Mono', monospace",
                            size: 10
                        }
                    }
                }
            },
            animation: {
                duration: 1000,
                easing: 'easeOutQuart'
            }
        }
    });

    sentimentBarChart = new Chart(barChartCanvas, {
        type: 'bar',
        data: {
            labels: ['Positive', 'Negative', 'Neutral'],
            datasets: [{
                label: 'Total Posts',
                data: [
                    processedData.barChartData.POSITIVE,
                    processedData.barChartData.NEGATIVE,
                    processedData.barChartData.NEUTRAL
                ],
                backgroundColor: [
                    'rgba(0, 255, 136, 0.7)',
                    'rgba(255, 51, 102, 0.7)',
                    'rgba(107, 140, 175, 0.7)'
                ],
                borderColor: [
                    '#00ff88',
                    '#ff3366',
                    '#6b8caf'
                ],
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y',
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                x: {
                    grid: {
                        color: 'rgba(125, 141, 160, 0.1)',
                        borderColor: 'rgba(125, 141, 160, 0.2)'
                    },
                    ticks: {
                        color: '#7d8da0',
                        font: {
                            family: "'IBM Plex Mono', monospace",
                            size: 10
                        }
                    }
                },
                y: {
                    grid: {
                        color: 'rgba(125, 141, 160, 0.1)',
                        borderColor: 'rgba(125, 141, 160, 0.2)'
                    },
                    ticks: {
                        color: '#7d8da0',
                        font: {
                            family: "'IBM Plex Mono', monospace",
                            size: 11,
                            weight: '600'
                        }
                    }
                }
            },
            animation: {
                duration: 1000,
                easing: 'easeOutQuart'
            }
        }
    });

    let tableHTML = `
        <table>
            <thead>
                <tr>
                    <th>Title</th>
                    <th>Subreddit</th>
                    <th>Sentiment</th>
                    <th>Content Type</th>
                    <th>Combined</th>
                </tr>
            </thead>
            <tbody>
    `;
    processedData.postsData.forEach(post => {
        const displayText = post.display_text || post.title || 'No content';
        const truncatedText = displayText.length > 100 ? 
            displayText.substring(0, 100) + '...' : displayText;
        
        let redditUrl = post.url;
        if (redditUrl && !redditUrl.startsWith('http')) {
            redditUrl = 'https://reddit.com' + redditUrl;
        }
        
        // Get content type information
        const contentType = post.content_type || 'N/A';
        const contentTypeDisplay = typeof contentType === 'string' ? contentType : 
            (contentType.Classification || 'N/A');
        const confidence = typeof contentType === 'object' ? 
            ` (${(contentType.Confidence * 100).toFixed(1)}%)` : '';
        
        // Create combined classification
        const sentiment = post.sentiment_type || 'UNKNOWN';
        const combined = contentTypeDisplay !== 'N/A' && contentTypeDisplay !== 'UNKNOWN' && contentTypeDisplay !== 'DISABLED' ? 
            `${sentiment}_${contentTypeDisplay}` : sentiment;
        
        tableHTML += `
            <tr>
                <td><a href="${redditUrl}" target="_blank">${truncatedText}</a></td>
                <td>r/${post.subreddit}</td>
                <td><span class="sentiment-badge ${sentiment.toLowerCase()}">${sentiment}</span></td>
                <td><span class="content-type-badge ${contentTypeDisplay.toLowerCase()}">${contentTypeDisplay}${confidence}</span></td>
                <td><span class="combined-badge ${combined.toLowerCase().replace('_', '-')}">${combined.replace('_', ' + ')}</span></td>
            </tr>
        `;
    });
    tableHTML += '</tbody></table>';
    postsTableDiv.innerHTML = tableHTML;
}

async function updateDashboard() {
    const selectedTicker = tickerSelect.value;
    const selectedType = typeSelect.value;
    const apiResponse = await fetchData(selectedTicker, selectedType);
    const processedData = processData(apiResponse);
    renderDashboard(processedData);
}

async function main() {
    TICKERS = await fetchTickers();
    populateTickerFilter();
    await updateDashboard();

    tickerSelect.addEventListener('change', updateDashboard);
    typeSelect.addEventListener('change', updateDashboard);
}

async function searchTicker() {
    const tickerInput = document.getElementById('ticker-input');
    const timeframeSelect = document.getElementById('timeframe-select');
    const searchBtn = document.getElementById('search-btn');
    const searchStatus = document.getElementById('search-status');
    const searchResults = document.getElementById('search-results');
    
    const ticker = tickerInput.value.trim().toUpperCase();
    const timeframe = timeframeSelect.value;
    
    if (!ticker) {
        showSearchStatus('Please enter a ticker symbol.', 'error');
        return;
    }
    
    if (!/^[A-Z]{1,5}$/.test(ticker)) {
        showSearchStatus('Please enter a valid ticker symbol (1-5 letters).', 'error');
        return;
    }
    
    searchBtn.disabled = true;
    searchBtn.textContent = 'Searching...';
    showSearchStatus('Searching for posts and analyzing sentiment...', 'loading');
    searchResults.style.display = 'none';
    
    try {
        const searchApiUrl = API_ENDPOINT.replace('/query', '/search');
        const response = await fetch(`${searchApiUrl}?ticker=${ticker}&timeframe=${timeframe}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Api-Key': API_KEY
            }
        });
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || `Request failed with status ${response.status}`);
        }
        
        const data = await response.json();
        
        displaySearchResults(data);
        showSearchStatus(`Found ${data.summary.total_items} items for ${ticker}`, 'success');
        
    } catch (error) {
        console.error('Search error:', error);
        showSearchStatus(`Error: ${error.message}`, 'error');
        searchResults.style.display = 'none';
    } finally {
        searchBtn.disabled = false;
        searchBtn.textContent = 'Search';
    }
}

function showSearchStatus(message, type) {
    const searchStatus = document.getElementById('search-status');
    searchStatus.textContent = message;
    searchStatus.className = `search-status ${type}`;
    searchStatus.style.display = 'block';
}

function displaySearchResults(data) {
    const searchResults = document.getElementById('search-results');
    const searchedTicker = document.getElementById('searched-ticker');

    searchedTicker.textContent = data.ticker;

    // Animate numbers counting up
    animateNumber('total-items', data.summary.total_items);
    animateNumber('total-posts', data.summary.posts);
    animateNumber('total-comments', data.summary.comments);
    animateNumber('avg-score', data.summary.average_score, true);

    createSearchSentimentChart(data.summary.sentiment_breakdown);

    displaySearchPosts(data.data);

    searchResults.style.display = 'block';
}

// Animate number counting effect
function animateNumber(elementId, targetValue, isDecimal = false) {
    const element = document.getElementById(elementId);
    const duration = 800; // milliseconds
    const steps = 30;
    const increment = targetValue / steps;
    let current = 0;
    let step = 0;

    const timer = setInterval(() => {
        step++;
        current += increment;

        if (step >= steps) {
            current = targetValue;
            clearInterval(timer);
        }

        if (isDecimal) {
            element.textContent = current.toFixed(1);
        } else {
            element.textContent = Math.floor(current);
        }
    }, duration / steps);
}

function createSearchSentimentChart(sentimentBreakdown) {
    const ctx = document.getElementById('search-sentiment-chart').getContext('2d');

    if (window.searchSentimentChart) {
        window.searchSentimentChart.destroy();
    }

    const colors = {
        'POSITIVE': '#00ff88',
        'NEGATIVE': '#ff3366',
        'NEUTRAL': '#6b8caf',
        'MIXED': '#ffd700'
    };

    const labels = Object.keys(sentimentBreakdown);
    const values = Object.values(sentimentBreakdown);
    const backgroundColors = labels.map(label => colors[label]);
    const borderColors = labels.map(label => colors[label]);

    window.searchSentimentChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: backgroundColors.map(color => color + '99'), // Add transparency
                borderColor: borderColors,
                borderWidth: 3,
                hoverOffset: 10
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#e8edf3',
                        font: {
                            family: "'JetBrains Mono', monospace",
                            size: 12
                        },
                        padding: 15,
                        usePointStyle: true,
                        pointStyle: 'circle'
                    }
                },
                tooltip: {
                    backgroundColor: '#12171f',
                    titleColor: '#00d9ff',
                    bodyColor: '#e8edf3',
                    borderColor: '#00d9ff',
                    borderWidth: 1,
                    padding: 12,
                    titleFont: {
                        family: "'JetBrains Mono', monospace",
                        size: 13,
                        weight: 'bold'
                    },
                    bodyFont: {
                        family: "'IBM Plex Mono', monospace",
                        size: 12
                    }
                }
            },
            animation: {
                duration: 1200,
                easing: 'easeOutQuart'
            }
        }
    });
}

function displaySearchPosts(posts) {
    const postsListDiv = document.getElementById('search-posts-list');
    
    if (!posts || posts.length === 0) {
        postsListDiv.innerHTML = '<p>No posts found for this search.</p>';
        return;
    }
    
    let tableHTML = `
        <table>
            <thead>
                <tr>
                    <th>Content</th>
                    <th>Type</th>
                    <th>Subreddit</th>
                    <th>Sentiment</th>
                    <th>Content Type</th>
                    <th>Combined</th>
                    <th>Score</th>
                </tr>
            </thead>
            <tbody>
    `;
    
    posts.forEach(item => {
        const isPost = item.type === 'post';
        const displayText = isPost ? item.title : item.body;
        const sentiment = item.sentiment ? item.sentiment.Sentiment : 'UNKNOWN';
        
        // Get content type information
        const contentType = item.content_type || {};
        const contentTypeDisplay = contentType.Classification || 'N/A';
        const contentConfidence = contentType.Confidence ? 
            ` (${(contentType.Confidence * 100).toFixed(1)}%)` : '';
        
        const truncatedText = displayText && displayText.length > 100 ? 
            displayText.substring(0, 100) + '...' : (displayText || 'No content');
        
        let redditUrl = item.url;
        if (redditUrl && !redditUrl.startsWith('http')) {
            redditUrl = 'https://reddit.com' + redditUrl;
        }
        
        // Create combined classification for display
        const combined = contentTypeDisplay !== 'N/A' && contentTypeDisplay !== 'UNKNOWN' && contentTypeDisplay !== 'DISABLED' ? 
            `${sentiment} + ${contentTypeDisplay}` : sentiment;
        
        tableHTML += `
            <tr>
                <td><a href="${redditUrl}" target="_blank">${truncatedText}</a></td>
                <td><span class="content-type ${isPost ? 'post' : 'comment'}">${isPost ? 'POST' : 'COMMENT'}</span></td>
                <td>r/${item.subreddit}</td>
                <td><span class="sentiment-badge ${sentiment.toLowerCase()}">${sentiment}</span></td>
                <td><span class="content-type-badge ${contentTypeDisplay.toLowerCase()}">${contentTypeDisplay}${contentConfidence}</span></td>
                <td><span class="combined-badge ${combined.toLowerCase().replace(' + ', '-').replace(/\s/g, '-')}">${combined}</span></td>
                <td>${item.score}</td>
            </tr>
        `;
    });
    
    tableHTML += '</tbody></table>';
    postsListDiv.innerHTML = tableHTML;
}

function getTimeAgo(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffDays > 0) {
        return `${diffDays}d ago`;
    } else if (diffHours > 0) {
        return `${diffHours}h ago`;
    } else {
        const diffMins = Math.floor(diffMs / (1000 * 60));
        return `${diffMins}m ago`;
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const tickerInput = document.getElementById('ticker-input');
    if (tickerInput) {
        tickerInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                searchTicker();
            }
        });
        
        tickerInput.addEventListener('input', function(e) {
            e.target.value = e.target.value.toUpperCase();
        });
    }
});

function openTab(evt, tabName) {
    const tabContents = document.getElementsByClassName('tab-content');
    for (let i = 0; i < tabContents.length; i++) {
        tabContents[i].classList.remove('active');
    }

    const tabButtons = document.getElementsByClassName('tab-button');
    for (let i = 0; i < tabButtons.length; i++) {
        tabButtons[i].classList.remove('active');
    }

    // Add glitch effect on tab switch
    const targetTab = document.getElementById(tabName);
    targetTab.classList.add('active');
    evt.currentTarget.classList.add('active');

    // Trigger animation reset
    targetTab.style.animation = 'none';
    setTimeout(() => {
        targetTab.style.animation = '';
    }, 10);
}

document.addEventListener('DOMContentLoaded', main);
