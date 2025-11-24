/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useRef } from "@odoo/owl";

export class InventoryDashboard extends Component {
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

        // 1. Monthly Purchases Bar Chart
        new Chart(this.chartRef.el, {
            type: 'bar',
            data: {
                labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'], // Mock labels for now
                datasets: [{
                    label: 'Monthly Purchases',
                    data: [12, 19, 3, 5, 2, 3], // Mock data
                    backgroundColor: '#334155', // Slate 700
                    borderRadius: 6,
                    barThickness: 24,
                    hoverBackgroundColor: '#1e293b' // Slate 800
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
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

        // 2. Top Vendors Doughnut Chart
        new Chart(this.doughnutRef.el, {
            type: 'doughnut',
            data: {
                labels: ['Vendor A', 'Vendor B', 'Vendor C'],
                datasets: [{
                    data: [30, 50, 20],
                    backgroundColor: ['#334155', '#64748b', '#94a3b8'], // Slate Palette
                    borderWidth: 0,
                    hoverOffset: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '75%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { font: { family: 'Inter' }, color: '#475569', usePointStyle: true, padding: 20 }
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
}

InventoryDashboard.template = "Idil.InventoryDashboard";

// Register the action
registry.category("actions").add("idil_inventory_dashboard", InventoryDashboard);
