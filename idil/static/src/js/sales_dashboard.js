/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useRef, useState } from "@odoo/owl";

export class SalesDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            stats: {},
            topProducts: {},
            hourlySales: {},
            categoryData: {},
            leaderboard: {},
            wastage: {},
            preorders: {},
        });

        // Chart refs
        this.monthlySalesRef = useRef("monthlySales");
        this.topProductsRef = useRef("topProducts");
        this.hourlySalesRef = useRef("hourlySales");
        this.categoryRef = useRef("category");
        this.leaderboardRef = useRef("leaderboard");

        onWillStart(async () => {
            await this.fetchAllData();
        });

        onMounted(() => {
            this.renderCharts();
        });
    }

    async fetchAllData() {
        // Fetch all data in parallel
        const [stats, topProducts, hourlySales, categoryData, leaderboard, wastage, preorders] = await Promise.all([
            this.orm.call("idil.dashboard", "get_dashboard_stats", []),
            this.orm.call("idil.dashboard", "get_top_products", [10]),
            this.orm.call("idil.dashboard", "get_hourly_sales", []),
            this.orm.call("idil.dashboard", "get_sales_by_category", []),
            this.orm.call("idil.dashboard", "get_salesperson_leaderboard", [5]),
            this.orm.call("idil.dashboard", "get_wastage_stats", []),
            this.orm.call("idil.dashboard", "get_preorder_stats", []),
        ]);

        this.state.stats = stats;
        this.state.topProducts = topProducts;
        this.state.hourlySales = hourlySales;
        this.state.categoryData = categoryData;
        this.state.leaderboard = leaderboard;
        this.state.wastage = wastage;
        this.state.preorders = preorders;
    }

    renderCharts() {
        // Check if Chart.js is available
        if (!window.Chart) {
            console.warn("Chart.js not loaded");
            return;
        }

        // 1. Top Products Chart (Horizontal Bar)
        if (this.topProductsRef.el) {
            new Chart(this.topProductsRef.el, {
                type: 'bar',
                data: {
                    labels: this.state.topProducts.labels || [],
                    datasets: [{
                        label: 'Revenue',
                        data: this.state.topProducts.revenues || [],
                        backgroundColor: '#334155', // Slate 700
                        borderRadius: 6,
                        barThickness: 20,
                        hoverBackgroundColor: '#1e293b'
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        title: {
                            display: true,
                            text: 'Top 10 Best Sellers',
                            font: { family: 'Inter', size: 16, weight: '600' },
                            color: '#1e293b',
                            padding: { bottom: 20 }
                        },
                        tooltip: {
                            backgroundColor: '#ffffff',
                            titleColor: '#1e293b',
                            bodyColor: '#475569',
                            borderColor: '#e2e8f0',
                            borderWidth: 1,
                            padding: 12,
                            cornerRadius: 8,
                            displayColors: false,
                            titleFont: { family: 'Inter', size: 13, weight: '600' },
                            bodyFont: { family: 'Inter', size: 12 }
                        }
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            grid: { borderDash: [4, 4], color: '#f1f5f9' },
                            ticks: { font: { family: 'Inter' }, color: '#94a3b8' }
                        },
                        y: {
                            grid: { display: false },
                            ticks: { font: { family: 'Inter' }, color: '#64748b' }
                        }
                    }
                }
            });
        }

        // 2. Hourly Sales Chart (Line)
        if (this.hourlySalesRef.el) {
            new Chart(this.hourlySalesRef.el, {
                type: 'line',
                data: {
                    labels: this.state.hourlySales.labels || [],
                    datasets: [{
                        label: 'Sales',
                        data: this.state.hourlySales.data || [],
                        backgroundColor: 'rgba(51, 65, 85, 0.05)', // Slate 700 low opacity
                        borderColor: '#334155', // Slate 700
                        borderWidth: 2,
                        pointBackgroundColor: '#ffffff',
                        pointBorderColor: '#334155',
                        pointBorderWidth: 2,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        title: {
                            display: true,
                            text: 'Hourly Sales (Today)',
                            font: { family: 'Inter', size: 16, weight: '600' },
                            color: '#1e293b',
                            padding: { bottom: 20 }
                        },
                        tooltip: {
                            backgroundColor: '#ffffff',
                            titleColor: '#1e293b',
                            bodyColor: '#475569',
                            borderColor: '#e2e8f0',
                            borderWidth: 1,
                            padding: 12,
                            cornerRadius: 8,
                            displayColors: false,
                            titleFont: { family: 'Inter', size: 13, weight: '600' },
                            bodyFont: { family: 'Inter', size: 12 }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: { borderDash: [4, 4], color: '#f1f5f9' },
                            ticks: { font: { family: 'Inter' }, color: '#94a3b8' }
                        },
                        x: {
                            grid: { display: false },
                            ticks: { font: { family: 'Inter' }, color: '#64748b' }
                        }
                    }
                }
            });
        }

        // 3. Category Breakdown (Doughnut)
        if (this.categoryRef.el) {
            new Chart(this.categoryRef.el, {
                type: 'doughnut',
                data: {
                    labels: this.state.categoryData.labels || [],
                    datasets: [{
                        data: this.state.categoryData.data || [],
                        backgroundColor: [
                            '#334155', '#475569', '#64748b', '#94a3b8', '#cbd5e1', '#e2e8f0'
                        ], // Slate Monochrome Gradient
                        borderWidth: 0,
                        hoverOffset: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '70%',
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: { font: { family: 'Inter' }, color: '#475569', usePointStyle: true, padding: 20 }
                        },
                        title: {
                            display: true,
                            text: 'Sales by Category',
                            font: { family: 'Inter', size: 16, weight: '600' },
                            color: '#1e293b',
                            padding: { bottom: 20 }
                        },
                        tooltip: {
                            backgroundColor: '#ffffff',
                            titleColor: '#1e293b',
                            bodyColor: '#475569',
                            borderColor: '#e2e8f0',
                            borderWidth: 1,
                            padding: 12,
                            cornerRadius: 8,
                            titleFont: { family: 'Inter', size: 13, weight: '600' },
                            bodyFont: { family: 'Inter', size: 12 }
                        }
                    }
                }
            });
        }

        // 4. Salesperson Leaderboard (Bar)
        if (this.leaderboardRef.el) {
            new Chart(this.leaderboardRef.el, {
                type: 'bar',
                data: {
                    labels: this.state.leaderboard.labels || [],
                    datasets: [{
                        label: 'Total Sales',
                        data: this.state.leaderboard.sales || [],
                        backgroundColor: '#059669', // Emerald 600 (Success)
                        borderRadius: 6,
                        barThickness: 24,
                        hoverBackgroundColor: '#047857'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        title: {
                            display: true,
                            text: 'Top Salespeople',
                            font: { family: 'Inter', size: 16, weight: '600' },
                            color: '#1e293b',
                            padding: { bottom: 20 }
                        },
                        tooltip: {
                            backgroundColor: '#ffffff',
                            titleColor: '#1e293b',
                            bodyColor: '#475569',
                            borderColor: '#e2e8f0',
                            borderWidth: 1,
                            padding: 12,
                            cornerRadius: 8,
                            displayColors: false,
                            titleFont: { family: 'Inter', size: 13, weight: '600' },
                            bodyFont: { family: 'Inter', size: 12 }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: { borderDash: [4, 4], color: '#f1f5f9' },
                            ticks: { font: { family: 'Inter' }, color: '#94a3b8' }
                        },
                        x: {
                            grid: { display: false },
                            ticks: { font: { family: 'Inter' }, color: '#64748b' }
                        }
                    }
                }
            });
        }
    }

    get stats() {
        return this.state.stats;
    }

    get wastage() {
        return this.state.wastage;
    }

    get preorders() {
        return this.state.preorders;
    }
}

SalesDashboard.template = "Idil.SalesDashboard";

// Register the action
registry.category("actions").add("idil_sales_dashboard", SalesDashboard);

