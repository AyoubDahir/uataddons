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
                        backgroundColor: '#4f6df5',
                        borderRadius: 4,
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
                            text: 'Top 10 Best Sellers'
                        }
                    },
                    scales: {
                        x: { beginAtZero: true },
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
                        backgroundColor: 'rgba(79, 109, 245, 0.1)',
                        borderColor: '#4f6df5',
                        borderWidth: 2,
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
                            text: 'Hourly Sales (Today)'
                        }
                    },
                    scales: {
                        y: { beginAtZero: true },
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
                            '#4f6df5', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'
                        ],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '70%',
                    plugins: {
                        legend: { position: 'bottom' },
                        title: {
                            display: true,
                            text: 'Sales by Category'
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
                        backgroundColor: '#10b981',
                        borderRadius: 4,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        title: {
                            display: true,
                            text: 'Top Salespeople'
                        }
                    },
                    scales: {
                        y: { beginAtZero: true },
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

