/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useRef } from "@odoo/owl";

export class SalesDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.stats = {};
        this.chartRef = useRef("chart");
        this.doughnutRef = useRef("doughnut");

        onWillStart(async () => {
            await this.fetchData();
        });

        onMounted(() => {
            this.renderCharts();
        });
    }

    async fetchData() {
        // Fetch data from the backend model
        this.stats = await this.orm.call("idil.dashboard", "get_dashboard_stats", []);
    }

    renderCharts() {
        // Check if Chart.js is available
        if (!window.Chart) {
            console.warn("Chart.js not loaded");
            return;
        }

        // 1. Monthly Sales Bar Chart
        new Chart(this.chartRef.el, {
            type: 'bar',
            data: {
                labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'], // Mock labels for now
                datasets: [{
                    label: 'Monthly Sales',
                    data: [15000, 22000, 18000, 25000, 30000, 28000], // Mock data
                    backgroundColor: '#4f6df5', // Volt Blue
                    borderRadius: 4,
                    barThickness: 20
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    y: { beginAtZero: true, grid: { borderDash: [2, 2] } },
                    x: { grid: { display: false } }
                }
            }
        });

        // 2. Customer Segmentation Doughnut Chart
        new Chart(this.doughnutRef.el, {
            type: 'doughnut',
            data: {
                labels: ['Retail', 'Wholesale', 'Online'],
                datasets: [{
                    data: [45, 30, 25],
                    backgroundColor: ['#4f6df5', '#10b981', '#f59e0b'], // Volt Colors
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '75%',
                plugins: {
                    legend: { position: 'bottom' }
                }
            }
        });
    }
}

SalesDashboard.template = "Idil.SalesDashboard";

// Register the action
registry.category("actions").add("idil_sales_dashboard", SalesDashboard);
